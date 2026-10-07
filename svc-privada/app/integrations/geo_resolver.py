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


class PadronNoDisponible(Exception):
    """svc-vivienda no respondió (o no está configurado) — para los flujos que
    NO pueden seguir sin el padrón oficial (sync del espejo, normalización)."""


def _base_url() -> str:
    if not settings.svc_vivienda_internal_url:
        raise PadronNoDisponible("SVC_VIVIENDA_INTERNAL_URL sin configurar")
    return settings.svc_vivienda_internal_url.rstrip("/")


async def resolver_localidades_estricto(
    items: list[tuple[str | None, str | None]]
) -> list[tuple[str | None, str | None]]:
    """Igual que `resolver_localidades` pero lanza `PadronNoDisponible` si la
    llamada falla, en vez de devolver todo sin resolver — quien normaliza datos
    no puede confundir "svc-vivienda caído" con "ninguna localidad matchea"."""
    if not items:
        return []
    base = _base_url()
    url = f"{base}/internal/geo/resolver-localidades"
    payload = {
        "items": [{"departamento": dep, "localidad": loc} for dep, loc in items],
        "origen": "privada",
    }
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise PadronNoDisponible(f"{url}: {exc!r}") from exc
    if resp.status_code != 200:
        raise PadronNoDisponible(f"{url} respondió {resp.status_code}")
    return [(r["id_geo"], r["match_tipo"]) for r in resp.json()["resultados"]]


async def resolver_localidades(
    items: list[tuple[str | None, str | None]]
) -> list[tuple[str | None, str | None]]:
    """Devuelve `[(id_geo, match_tipo), ...]` alineado con `items`. Ante
    cualquier fallo (red, servicio caído, timeout) devuelve todo `(None,
    None)` — el rollup sigue su curso sin `id_geo` resuelto."""
    vacio: list[tuple[str | None, str | None]] = [(None, None)] * len(items)
    if not items or not settings.resolver_localidades_enabled or not settings.svc_vivienda_internal_url:
        return vacio
    try:
        return await resolver_localidades_estricto(items)
    except PadronNoDisponible as exc:  # tolerante por diseño, nunca rompe el rollup
        logger.warning("geo_resolver: fallo resolviendo localidades: %s", exc)
        return vacio


async def fetch_padron() -> list[dict]:
    """Padrón oficial completo (`GET /internal/geo/padron` de svc-vivienda) para
    el espejo `priv_geo_localidades` (ADR-026). Lanza `PadronNoDisponible` ante
    cualquier fallo o respuesta vacía — el espejo nunca se pisa con nada."""
    base = _base_url()
    url = f"{base}/internal/geo/padron"
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise PadronNoDisponible(f"{url}: {exc!r}") from exc
    if resp.status_code != 200:
        raise PadronNoDisponible(f"{url} respondió {resp.status_code}")
    filas = resp.json()
    if not isinstance(filas, list) or not filas:
        raise PadronNoDisponible(f"{url} devolvió un padrón vacío")
    return filas
