"""Cliente del WFS público de IDECOR (Catastro de Córdoba).

Ver docs/files/spec-mi-lugar-valor-fiscal-idecor.md §4. Todo lo que devuelve la
fuente está en EPSG:22174 (Gauss-Krüger faja 4); los filtros CQL con `SRID=4326`
no devuelven nada (probado 2026-10-19), así que los puntos se reproyectan acá
antes de consultar.

Las respuestas se parsean desde bytes como UTF-8 (GeoServer a veces declara otra
codificación) y con `parse_float=Decimal` para que los montos no pierdan
centavos al sumarse.
"""
import json
import logging
import re
import time
from decimal import Decimal
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Campos de `idecor:parcelas` que la spec necesita (§4.1). Si falta alguno, la
# fuente cambió de esquema y la consulta falla entera.
CAMPOS_PARCELA = (
    "Nomenclatura",
    "Nro_Cuenta",
    "Tipo_Parcela",
    "Estado",
    "desig_oficial",
    "localidad",
    "Valuacion",
    "Valuacion_Tierra_Urbana",
    "Valuacion_Tierra_Rural",
    "Valuacion_Mejoras",
    "Superficie_Tierra_Urbana",
    "Superficie_Tierra_Rural",
    "vigencia_desde",
)
CAMPOS_PARCELA_OBLIGATORIOS = (
    "Nomenclatura",
    "Valuacion",
    "Valuacion_Tierra_Urbana",
    "Valuacion_Tierra_Rural",
    "Valuacion_Mejoras",
    "Superficie_Tierra_Urbana",
    "Superficie_Tierra_Rural",
    "vigencia_desde",
)

_CAPA_MAPA_VALORES = re.compile(r"idecor:valor_tierra_(urbana|rural)_(\d{4})")
_CACHE_ANIO_SEGUNDOS = 12 * 3600
_cache_anio: tuple[float, int | None] | None = None


class CatastroFallido(Exception):
    """La consulta a IDECOR falló entera (red, HTTP, respuesta ilegible o esquema)."""


def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.idecor_timeout_segundos)


async def _get(client: httpx.AsyncClient, params: dict[str, str]) -> bytes:
    try:
        resp = await client.get(settings.idecor_wfs_url, params=params)
    except httpx.HTTPError as exc:
        raise CatastroFallido(f"IDECOR no respondió: {exc!r}") from exc
    if resp.status_code != 200:
        raise CatastroFallido(f"IDECOR respondió {resp.status_code}")
    return resp.content


async def get_features(
    client: httpx.AsyncClient, capa: str, cql: str, propiedades: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Devuelve los features de `capa` que cumplen `cql`. GeoServer contesta 200
    con un XML de excepción cuando el filtro o la capa son inválidos: eso
    también se trata como falla entera."""
    contenido = await _get(client, {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": f"idecor:{capa}",
        "outputFormat": "application/json",
        "propertyName": ",".join(propiedades),
        "CQL_FILTER": cql,
    })
    try:
        data = json.loads(contenido.decode("utf-8", errors="replace"), parse_float=Decimal)
        return list(data["features"])
    except (ValueError, KeyError, TypeError) as exc:
        raise CatastroFallido(f"respuesta ilegible de IDECOR para {capa}: {contenido[:300]!r}") from exc


def validar_parcela(props: dict[str, Any]) -> None:
    faltan = [c for c in CAMPOS_PARCELA_OBLIGATORIOS if c not in props]
    if faltan:
        raise CatastroFallido(f"idecor:parcelas cambió de esquema, faltan campos: {', '.join(faltan)}")


async def anio_mapa_valores(client: httpx.AsyncClient) -> int | None:
    """Año más reciente con las dos capas del mapa de valores publicadas
    (`valor_tierra_urbana_AAAA` y `valor_tierra_rural_AAAA`). Se cachea en
    memoria: el mapa se publica una vez por año."""
    global _cache_anio
    if _cache_anio and time.monotonic() - _cache_anio[0] < _CACHE_ANIO_SEGUNDOS:
        return _cache_anio[1]

    contenido = await _get(client, {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"})
    anios: dict[str, set[int]] = {"urbana": set(), "rural": set()}
    for tipo, anio in _CAPA_MAPA_VALORES.findall(contenido.decode("utf-8", errors="replace")):
        anios[tipo].add(int(anio))
    comunes = anios["urbana"] & anios["rural"]
    resultado = max(comunes) if comunes else None
    _cache_anio = (time.monotonic(), resultado)
    return resultado


def punto_wkt(x: float, y: float) -> str:
    return f"POINT({x:.2f} {y:.2f})"


def punto_interior(geometria: dict[str, Any] | None) -> tuple[float, float] | None:
    """Centroide del anillo exterior del polígono más grande (fórmula del
    área). Alcanza para ubicar la zona de valor rural, que son polígonos
    grandes; si cae fuera de una parcela muy cóncava, el error es de zona
    vecina, aceptado como referencia (spec §4.2)."""
    if not geometria or not geometria.get("coordinates"):
        return None
    coords = geometria["coordinates"]
    poligonos = coords if geometria.get("type") == "MultiPolygon" else [coords]
    mejor: tuple[float, float, float] | None = None
    for poligono in poligonos:
        anillo = [(float(p[0]), float(p[1])) for p in poligono[0]]
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(anillo, anillo[1:] + anillo[:1]):
            cruz = x0 * y1 - x1 * y0
            a += cruz
            cx += (x0 + x1) * cruz
            cy += (y0 + y1) * cruz
        if a == 0:
            continue
        area = abs(a / 2)
        if mejor is None or area > mejor[0]:
            mejor = (area, cx / (3 * a), cy / (3 * a))
    return (mejor[1], mejor[2]) if mejor else None
