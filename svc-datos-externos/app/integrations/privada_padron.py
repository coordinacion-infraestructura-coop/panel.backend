"""Padrón político de svc-privada (ADR-027, spec-padron-politico-gobierno-privada.md §3). Mismo
patrón que las demás federaciones: endpoint IAM-only, ID token con la URL del servicio como
audiencia, flag apagado en `config.py` que `cloudbuild.yaml` enciende.

Devuelve None si está apagado o falla: el sync deja lo último leído y lo anota en el log.
"""
import logging

import httpx

from app.config import settings
from app.integrations.geo_resolver import _mint_id_token

logger = logging.getLogger(__name__)


async def padron_privada() -> list[dict] | None:
    if not settings.privada_padron_fetch_enabled or not settings.svc_privada_internal_url:
        return None
    base = settings.svc_privada_internal_url.rstrip("/")
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{base}/internal/privada/padron-politico", headers=headers)
        if resp.status_code != 200:
            logger.warning("padrón de Privada: svc-privada respondió %s", resp.status_code)
            return None
        filas = resp.json()
        return filas if isinstance(filas, list) else None
    except Exception as exc:  # noqa: BLE001 — tolerante: queda lo último leído
        logger.warning("padrón de Privada: no se pudo leer: %r", exc)
        return None
