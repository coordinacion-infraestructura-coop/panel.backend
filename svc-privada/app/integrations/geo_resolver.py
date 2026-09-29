"""Resuelve (departamento, localidad) contra el padrón oficial de svc-vivienda
(ADR-024, docs/files/spec-normalizacion-localidades.md §4.5) — aplicado al
rollup territorial, no persistido por gestión (svc-privada mantiene su propio
padrón, priv_geo_localidades, ADR-012; esto sólo alimenta el agregado que
consume resumen_territorial, para que sus localidades matcheen contra la
misma base que Vivienda/Gasífera/Gralgob).

Llamada HTTP saliente best-effort — nunca lanza; si falla, el rollup se
devuelve sin `id_geo` resuelto (mismo criterio tolerante que el resto de las
integraciones salientes del proyecto). Mismo patrón de ID token que
`app/auth.py::_fetch_portal_user`.
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
    None)` — el rollup sigue su curso sin `id_geo` resuelto."""
    vacio: list[tuple[str | None, str | None]] = [(None, None)] * len(items)
    if not items or not settings.resolver_localidades_enabled or not settings.svc_vivienda_internal_url:
        return vacio

    base = settings.svc_vivienda_internal_url.rstrip("/")
    url = f"{base}/internal/geo/resolver-localidades"
    payload = {
        "items": [{"departamento": dep, "localidad": loc} for dep, loc in items],
        "origen": "privada",
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
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño, nunca rompe el rollup
        logger.warning("geo_resolver: fallo resolviendo localidades (%s): %r", url, exc)
        return vacio
