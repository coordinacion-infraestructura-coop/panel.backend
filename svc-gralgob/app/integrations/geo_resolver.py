"""Resuelve (departamento, localidad) contra el padrón oficial de svc-vivienda
en sync-time (ADR-024, docs/files/spec-normalizacion-localidades.md §4.5).

Llamada HTTP saliente best-effort — nunca lanza; si falla, el sync persiste
las filas sin `id_geo`/`match_tipo` resueltos en vez de abortar. Mismo patrón
de ID token que `app/integrations/notificaciones_vivienda.py`.
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _mint_id_token(audience: str) -> str | None:
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        return id_token.fetch_id_token(GoogleRequest(), audience)
    except Exception as exc:  # noqa: BLE001 — sin credenciales (local/test) es esperable
        logger.warning("geo_resolver: no se pudo mintear ID token: %s", exc)
        return None


async def resolver_localidades(
    items: list[tuple[str | None, str | None]]
) -> list[tuple[str | None, str | None]]:
    """Devuelve `[(id_geo, match_tipo), ...]` alineado con `items`. Ante
    cualquier fallo (red, servicio caído, timeout) devuelve todo `(None,
    None)` — el sync sigue su curso sin bloquear (mismo criterio tolerante
    que `notificaciones_vivienda`)."""
    vacio: list[tuple[str | None, str | None]] = [(None, None)] * len(items)
    if not items or not settings.resolver_localidades_enabled or not settings.svc_vivienda_internal_url:
        return vacio

    base = settings.svc_vivienda_internal_url.rstrip("/")
    url = f"{base}/internal/geo/resolver-localidades"
    payload = {
        "items": [{"departamento": dep, "localidad": loc} for dep, loc in items],
        "origen": "atp",
    }
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.warning("geo_resolver: %s respondió %s", url, resp.status_code)
            return vacio
        resultados = resp.json()["resultados"]
        return [(r["id_geo"], r["match_tipo"]) for r in resultados]
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño, nunca rompe el sync
        logger.warning("geo_resolver: fallo resolviendo localidades (%s): %r", url, exc)
        return vacio
