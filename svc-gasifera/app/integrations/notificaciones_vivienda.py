"""Notifica al panel de notificaciones de svc-vivienda (ADR-019/ADR-023) cuando
el sync de gas_pit detecta una acción territorial NUEVA (no una actualización).

Llamada HTTP saliente best-effort — nunca lanza, cualquier fallo se loguea y el
sync sigue su curso. Mismo patrón de ID token que `app/auth.py::_fetch_portal_user`
(SA de runtime, audiencia = URL base de svc-vivienda).
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
        logger.warning("notificaciones_vivienda: no se pudo mintear ID token: %s", exc)
        return None


async def notificar_accion_nueva(
    *, localidad: str | None, departamento: str | None, accion: str | None
) -> None:
    """Best-effort: nunca lanza. Llamar por cada acción territorial NUEVA detectada
    en el sync (ver `app/gas_pit/sync.py::sync_from_sheet`, hoja ACCIONES TERRITORIO)."""
    if not settings.notificar_fila_nueva_enabled or not settings.svc_vivienda_internal_url:
        return

    loc = localidad or "(sin localidad)"
    dep = departamento or "(sin departamento)"
    acc = accion or "(sin detalle)"

    base = settings.svc_vivienda_internal_url.rstrip("/")
    url = f"{base}/internal/notificaciones"
    payload = {
        "titulo": "Nueva acción territorial de gas",
        "mensaje": f"La localidad {loc}, {dep} sumó obra de gas {acc}.",
        "nivel": "info",
        "origen": "gas_pit_sync",
        "destino_tipo": "secretaria",
        "destino_valor": "gasifera",
    }
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.warning("notificaciones_vivienda: %s respondió %s", url, resp.status_code)
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño, nunca rompe el sync
        logger.warning("notificaciones_vivienda: fallo notificando (%s): %r", url, exc)
