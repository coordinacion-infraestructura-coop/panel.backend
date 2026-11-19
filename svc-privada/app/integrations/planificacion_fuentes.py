"""Cruces de la planificación de programas con los servicios que ya tienen el dato (ADR-036,
docs/files/spec-privada-planificacion-programas.md §6).

Todo por IAM (ID token con la URL del servicio como audiencia) y **sólo lectura**:

| fuente         | servicio            | endpoint                                            |
|----------------|---------------------|-----------------------------------------------------|
| cordon_cuneta, cordoba_hogar, mi_lugar | svc-vivienda | `GET /internal/planificacion/lineas?programa=`  |
| gas_pit        | svc-gasifera        | `GET /internal/gasifera/rollup-territorial`         |
| atp            | svc-gralgob         | `GET /internal/atp/rollup-territorial`              |
| (todas)        | svc-datos-externos  | `GET /internal/datos-externos/planificacion/localidades` |

Fail-open: si una fuente no responde, su columna queda "sin dato" y la planilla sigue editable.
**Nunca se devuelve "no está" cuando en realidad no se pudo consultar.** Caché en memoria de
5 minutos por fuente, para no consultar a los otros servicios en cada recarga.
"""
import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.integrations.geo_resolver import _mint_id_token

logger = logging.getLogger(__name__)

TTL_SEGUNDOS = 300
_cache: dict[str, tuple[float, Any]] = {}

FUENTES_VIVIENDA = ("cordon_cuneta", "cordoba_hogar", "mi_lugar")


class FuenteNoDisponible(Exception):
    pass


async def _get(base_url: str, path: str, params: dict | None = None) -> Any:
    if not settings.planificacion_fetch_enabled:
        raise FuenteNoDisponible("PLANIFICACION_FETCH_ENABLED está apagado")
    if not base_url:
        raise FuenteNoDisponible(f"URL interna sin configurar para {path}")
    clave = f"{base_url}{path}?{sorted((params or {}).items())}"
    hit = _cache.get(clave)
    if hit and time.monotonic() - hit[0] < TTL_SEGUNDOS:
        return hit[1]
    base = base_url.rstrip("/")
    token = _mint_id_token(base)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{base}{path}", params=params, headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise FuenteNoDisponible(f"{path}: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise FuenteNoDisponible(f"{path} respondió {resp.status_code}")
    datos = resp.json()
    _cache[clave] = (time.monotonic(), datos)
    return datos


def limpiar_cache() -> None:
    _cache.clear()


def _atp_estado(monto_total: float | None, entregado: float) -> dict:
    # Mismo criterio que resumen_territorial.aggregations.resumen_atp_estado (svc-vivienda).
    if not monto_total or monto_total <= 0:
        return {"label": "Sin estado", "bg": "#e5e7eb", "text_color": "#374151"}
    if entregado <= 0:
        return {"label": "Pendiente", "bg": "#FEF3C7", "text_color": "#92400E"}
    if entregado >= monto_total:
        return {"label": "Pagado", "bg": "#D1FAE5", "text_color": "#065F46"}
    return {"label": "Parcial", "bg": "#DBEAFE", "text_color": "#1E40AF"}


async def lineas_del_panel(fuente: str) -> tuple[dict[str, list[dict]], int]:
    """→ ({id_geo: [líneas normalizadas]}, filas_sin_id_geo). Lanza FuenteNoDisponible."""
    por_geo: dict[str, list[dict]] = {}
    sin_id_geo = 0
    if fuente in FUENTES_VIVIENDA:
        datos = await _get(settings.svc_vivienda_internal_url, "/internal/planificacion/lineas", {"programa": fuente})
        for li in datos.get("lineas", []):
            por_geo.setdefault(li["id_geo"], []).append(li)
        sin_id_geo = int(datos.get("sin_id_geo") or 0)
    elif fuente == "gas_pit":
        for r in await _get(settings.svc_gasifera_internal_url, "/internal/gasifera/rollup-territorial"):
            if not r.get("id_geo"):
                sin_id_geo += 1
                continue
            en_curso = int(r.get("en_curso") or 0)
            por_geo.setdefault(r["id_geo"], []).append({
                "estado_general": (
                    {"label": f"En curso ({en_curso})", "bg": "#DBEAFE", "text_color": "#1E40AF"} if en_curso
                    else {"label": "Cumplido", "bg": "#D1FAE5", "text_color": "#065F46"}
                ),
                "ok_gob": None, "convenio_firmado": None, "fecha_firma_convenio": None,
                "monto": r.get("monto_solicitado_sum"),
            })
    elif fuente == "atp":
        for r in await _get(settings.svc_gralgob_internal_url, "/internal/atp/rollup-territorial"):
            if not r.get("id_geo"):
                sin_id_geo += 1
                continue
            por_geo.setdefault(r["id_geo"], []).append({
                "estado_general": _atp_estado(r.get("monto_total_sum"), float(r.get("entregado_sum") or 0)),
                "ok_gob": None, "convenio_firmado": None, "fecha_firma_convenio": None,
                "monto": r.get("monto_total_sum"),
            })
    else:
        raise FuenteNoDisponible(f"fuente desconocida: {fuente}")
    return por_geo, sin_id_geo


async def datos_externos() -> tuple[dict[str, dict], dict | None]:
    """→ ({id_geo: {coparticipacion_anual?, visita_gobernador?}}, coparticipacion_periodo)."""
    datos = await _get(settings.svc_datos_externos_internal_url, "/internal/datos-externos/planificacion/localidades")
    return {f["id_geo"]: f for f in datos.get("localidades", [])}, datos.get("coparticipacion_periodo")
