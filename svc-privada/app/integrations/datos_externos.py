"""Padrón político combinado (Gobierno, y Privada donde Gobierno no tiene dato) desde
svc-datos-externos (ADR-027, docs/files/spec-padron-politico-gobierno-privada.md §3).

A diferencia de las federaciones tolerantes, acá una falla lanza `PadronPoliticoNoDisponible`:
quien escribe el padrón no puede confundir "svc-datos-externos caído" con "no hay datos".
"""
import httpx

from app.config import settings
from app.integrations.geo_resolver import _mint_id_token


class PadronPoliticoNoDisponible(Exception):
    """Sync apagado, sin URL, o svc-datos-externos no respondió bien."""


async def fetch_padron_combinado() -> list[dict]:
    if not settings.padron_politico_sync_enabled:
        raise PadronPoliticoNoDisponible("PADRON_POLITICO_SYNC_ENABLED está apagado")
    if not settings.svc_datos_externos_internal_url:
        raise PadronPoliticoNoDisponible("SVC_DATOS_EXTERNOS_INTERNAL_URL sin configurar")
    base = settings.svc_datos_externos_internal_url.rstrip("/")
    token = _mint_id_token(base)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{base}/internal/datos-externos/padron-politico", headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise PadronPoliticoNoDisponible(f"svc-datos-externos no respondió: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise PadronPoliticoNoDisponible(f"svc-datos-externos respondió {resp.status_code}")
    filas = resp.json()
    if not isinstance(filas, list) or not filas:
        raise PadronPoliticoNoDisponible("svc-datos-externos devolvió un padrón vacío")
    return filas
