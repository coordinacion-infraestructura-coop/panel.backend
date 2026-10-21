"""ATP Interno por localidad desde svc-gralgob, para el Resumen general del tablero
(spec-atp-interno.md §4.2 y §4.3). Mismo patrón que las federaciones de ADR-016/021/022:
endpoint IAM-only, ID token con la URL del servicio como audiencia, flag que en `config.py` está
apagado y `cloudbuild.yaml` enciende.

Devuelve None si la federación está apagada o falla: el Resumen lo marca como no disponible y
nunca muestra un total que parezca completo sin serlo.
"""
import logging

import httpx

from app.config import settings
from app.integrations.geo_resolver import _mint_id_token

logger = logging.getLogger(__name__)


async def atp_por_localidad(anio: int) -> dict[str, float] | None:
    if not settings.atp_interno_fetch_enabled or not settings.svc_gralgob_internal_url:
        return None
    base = settings.svc_gralgob_internal_url.rstrip("/")
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{base}/internal/atp-interno/por-localidad", params={"anio": anio}, headers=headers)
        if resp.status_code != 200:
            logger.warning("atp_interno: svc-gralgob respondió %s", resp.status_code)
            return None
        return {f["codigo_indec"]: float(f["monto"]) for f in resp.json()}
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño: el Resumen sale sin ATP
        logger.warning("atp_interno: no se pudo leer ATP Interno de svc-gralgob: %r", exc)
        return None
