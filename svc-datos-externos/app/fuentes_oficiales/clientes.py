"""Clientes HTTP de las fuentes oficiales (spec-datos-externos-fuentes-oficiales.md §2).

Todas públicas y sin autenticación. Cualquier falla de red, HTTP o respuesta
ilegible levanta `FuenteFallida`: la fuente entera queda en `error` y no se toca
lo que había guardado.
"""
import csv
import io
import json
from decimal import Decimal
from typing import Any

import httpx

from app.config import settings


class FuenteFallida(Exception):
    pass


def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.fuentes_oficiales_timeout_segundos, follow_redirects=True)


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None, headers: dict | None = None) -> bytes:
    try:
        resp = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise FuenteFallida(f"{url} no respondió: {exc!r}") from exc
    if resp.status_code != 200:
        raise FuenteFallida(f"{url} respondió {resp.status_code}")
    return resp.content


def _json(contenido: bytes, origen: str) -> Any:
    try:
        return json.loads(contenido.decode("utf-8", errors="replace"), parse_float=Decimal)
    except ValueError as exc:
        raise FuenteFallida(f"respuesta ilegible de {origen}: {contenido[:300]!r}") from exc


async def arcgis_query(
    client: httpx.AsyncClient, capa: str, *, geometria: bool = False
) -> list[dict[str, Any]]:
    """Todas las filas de una capa del ArcGIS de Estadística, paginando.
    `capa` = "<carpeta>/<servicio>/FeatureServer/<n>". Con `geometria`, cada
    fila trae además `__rings__` (WGS84, simplificada)."""
    url = f"{settings.estadistica_arcgis_base.rstrip('/')}/{capa}/query"
    filas: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "where": "1=1", "outFields": "*", "f": "json",
            "resultOffset": offset, "resultRecordCount": 1000,
            "returnGeometry": "true" if geometria else "false",
        }
        if geometria:
            params.update({"outSR": 4326, "maxAllowableOffset": 0.0002, "geometryPrecision": 6})
        data = _json(await _get(client, url, params), capa)
        if not isinstance(data, dict) or "error" in data or "features" not in data:
            raise FuenteFallida(f"ArcGIS {capa}: {str(data)[:300]}")
        lote = data["features"]
        for f in lote:
            fila = dict(f.get("attributes") or {})
            if geometria:
                fila["__rings__"] = [[[float(x), float(y)] for x, y in anillo] for anillo in (f.get("geometry") or {}).get("rings", [])]
            filas.append(fila)
        if not data.get("exceededTransferLimit") or not lote:
            return filas
        offset += len(lote)


async def wfs_features(
    client: httpx.AsyncClient, capa: str, *, propiedades: tuple[str, ...] | None = None, wgs84: bool = True
) -> list[dict[str, Any]]:
    """Todos los features de una capa del WFS de IDECOR (GeoJSON)."""
    params: dict[str, Any] = {
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "typeName": f"idecor:{capa}", "outputFormat": "application/json",
    }
    if wgs84:
        params["srsName"] = "EPSG:4326"
    if propiedades:
        params["propertyName"] = ",".join(propiedades)
    data = _json(await _get(client, settings.idecor_wfs_url, params), f"IDECOR {capa}")
    if not isinstance(data, dict) or "features" not in data:
        raise FuenteFallida(f"IDECOR {capa}: respuesta sin features")
    return data["features"]


async def renabap_csv(client: httpx.AsyncClient) -> list[dict[str, str]]:
    """CSV del RENABAP desde el servidor de datos de Poblaciones. El servidor
    pide un `Referer` del visor; el cuerpo viene en UTF-8 aunque el header
    declare ISO-8859-1."""
    contenido = await _get(
        client, settings.renabap_csv_url, headers={"Referer": "https://mapa.poblaciones.org/map/", "User-Agent": "Mozilla/5.0"},
    )
    texto = contenido.decode("utf-8", errors="replace")
    if not texto.startswith('"ID Renabap"'):
        raise FuenteFallida(f"RENABAP: respuesta inesperada: {texto[:200]!r}")
    csv.field_size_limit(10**9)
    return list(csv.DictReader(io.StringIO(texto)))
