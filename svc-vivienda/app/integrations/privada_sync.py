"""Vinculación Vivienda -> Privada (ADR-020, `docs/files/spec-vinculacion-vivienda-privada.md`).

Llamada HTTP inline, best-effort, disparada desde `crear_*`/`actualizar_*` de
Cordón Cuneta, Córdoba Hogar y Mi Lugar (dentro de la misma transacción que el
caso — igual patrón que `resumen_territorial.service.fetch_privada_lineas`, pero
en sentido push). Nunca lanza: cualquier fallo se loguea y se registra en
`viv_privada_sync_log`; el alta/edición del caso de Vivienda sigue su curso normal.
"""
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.config import settings
from app.integrations.models import VinculoPrivada, VinculoPrivadaSyncLog
from app.notificaciones import service as notificaciones_service

logger = logging.getLogger(__name__)

# Actor sintético para las notificaciones que genera este módulo — no hay usuario
# real detrás de una sincronización automática (mismo patrón que `_SCHEDULER_ACTOR`
# en `app/internal/router.py`).
_SYNC_ACTOR = AuthUser(uid="privada-sync", email="privada-sync", role="system", secretarias=[])

# "Campo de trabajo" (categoria_id), programa asociado y área en priv_categorias /
# priv_programas / priv_areas — ids semilla de la migración 0002 de svc-privada.
_CATEGORIA_POR_TIPO = {"cc": 1756700000003, "ch": 1756700000001, "ml": 1756700000002}
_PROGRAMA_POR_TIPO = {"cc": 1756700001003, "ch": 1756700001001, "ml": 1756700001002}
_AREA_DGV = 1756700002001
# Confirmado 2026-09-14 contra el catálogo real (docs/data/cat_ministerio_agencia.json,
# volcado de priv_cat_ministerio_agencia): MIN_GOBIERNO = "Ministerio de Gobierno", activo.
_MINISTERIO_AGENCIA_ID = "MIN_GOBIERNO"

# resultado de svc-privada (4 valores) -> estado_vinculo local (3 valores, CHECK).
_ESTADO_VINCULO = {
    "LINKED_NEW": "LINKED",
    "LINKED_EXISTING": "LINKED",
    "PENDING_REVIEW": "PENDING_REVIEW",
    "ERROR": "ERROR",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mint_id_token(audience: str) -> str | None:
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token

        return id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    except Exception as exc:  # noqa: BLE001 — sin credenciales (local/test) es esperable
        logger.warning("privada_sync: no se pudo mintear ID token: %s", exc)
        return None


def _ok_valor(ok_gob: str | None) -> str:
    return "SI" if (ok_gob or "").strip().upper() == "SI" else "PENDIENTE"


async def _notificar_creacion(
    db: AsyncSession, *, caso_tipo: str, caso_id: str, localidad: str, departamento: str,
    gestion_id: str | None,
) -> None:
    await notificaciones_service.crear(db, _SYNC_ACTOR, {
        "titulo": "Nueva gestión creada en Privada",
        "mensaje": (
            f"La localidad {localidad}, {departamento} generó una gestión nueva en Privada "
            f"(caso {caso_tipo.upper()} {caso_id})."
        ),
        "nivel": "info",
        "origen": "privada_sync",
        "destino_tipo": "secretaria",
        "destino_valor": "privada",
    })


async def _notificar_correccion(
    db: AsyncSession, *, caso_tipo: str, caso_id: str, localidad: str, departamento: str, diff: dict
) -> None:
    campos = ", ".join(diff.keys())
    await notificaciones_service.crear(db, _SYNC_ACTOR, {
        "titulo": "Gestión de Privada actualizada por sincronización",
        "mensaje": (
            f"La localidad {localidad}, {departamento} tuvo su gestión de Privada actualizada "
            f"por sincronización (caso {caso_tipo.upper()} {caso_id}): {campos}."
        ),
        "nivel": "info",
        "origen": "privada_sync",
        "destino_tipo": "secretaria",
        "destino_valor": "privada",
    })


async def _notificar_pendiente_revision(
    db: AsyncSession, *, caso_tipo: str, caso_id: str, localidad: str, departamento: str,
    motivo: str | None,
) -> None:
    await notificaciones_service.crear(db, _SYNC_ACTOR, {
        "titulo": "Caso pendiente de vincular con Privada",
        "mensaje": (
            f"La localidad {localidad}, {departamento} (caso {caso_tipo.upper()} {caso_id}) "
            f"no se pudo vincular automáticamente a una gestión de Privada "
            f"({motivo or 'match ambiguo'}). Requiere revisión manual."
        ),
        "nivel": "advertencia",
        "origen": "privada_sync",
        "destino_tipo": "secretaria",
        "destino_valor": "privada",
    })


async def _upsert_vinculo(
    db: AsyncSession, *, caso_tipo: str, caso_id: str, id_legacy: str,
    resultado: str, gestion_id: str | None, motivo: str | None,
) -> None:
    vinculo = (
        await db.execute(
            select(VinculoPrivada).where(
                VinculoPrivada.caso_tipo == caso_tipo, VinculoPrivada.caso_id == caso_id
            )
        )
    ).scalar_one_or_none()
    now = _now()
    if vinculo is None:
        vinculo = VinculoPrivada(caso_tipo=caso_tipo, caso_id=caso_id, id_legacy=id_legacy, created_at=now)
        db.add(vinculo)

    exito = resultado in ("LINKED_NEW", "LINKED_EXISTING")
    estado_nuevo = _ESTADO_VINCULO.get(resultado, "ERROR")
    # Regla de no-flapping (spec §8): un ERROR transitorio no degrada un vínculo que
    # ya estaba LINKED — sólo se actualiza `ultimo_intento_at`.
    if exito or vinculo.estado_vinculo != "LINKED":
        vinculo.estado_vinculo = estado_nuevo
        vinculo.motivo = motivo
        if gestion_id is not None:
            vinculo.gestion_id = gestion_id
    vinculo.id_legacy = id_legacy
    vinculo.ultimo_intento_at = now
    if exito:
        vinculo.ultimo_ok_at = now
    vinculo.updated_at = now
    await db.flush()


async def sync_gestion_privada(
    db: AsyncSession, *, caso_tipo: str, caso_id: str,
    nro_expediente: str | None, localidad: str, departamento: str, ok_gob: str | None,
) -> None:
    """Best-effort, nunca lanza. Llamar SIEMPRE después de `log_audit(...)` y antes
    del `return` de `crear_*`/`actualizar_*` en cordon_cuneta, cordoba_hogar, mi_lugar."""
    if not settings.privada_sync_gestiones_enabled or not settings.svc_privada_internal_url:
        return

    id_legacy = f"vivienda:{caso_tipo}:{caso_id}"
    ok_valor = _ok_valor(ok_gob)
    payload = {
        "caso_tipo": caso_tipo,
        "caso_id": caso_id,
        "id_legacy": id_legacy,
        "nro_expediente": nro_expediente,
        "localidad": localidad,
        "departamento": departamento,
        "categoria_id": _CATEGORIA_POR_TIPO.get(caso_tipo),
        "programa_id": _PROGRAMA_POR_TIPO.get(caso_tipo),
        "area_id": _AREA_DGV,
        "ministerio_agencia_id": _MINISTERIO_AGENCIA_ID,
        "ok_gobernador": ok_valor,
        "ok_ministro": ok_valor,
    }

    base = settings.svc_privada_internal_url.rstrip("/")
    url = base + settings.privada_gestiones_sync_internal_path

    resultado, gestion_id, motivo, diff = "ERROR", None, None, None
    http_status, error_detalle = None, None
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload, headers=headers)
        http_status = resp.status_code
        if resp.status_code != 200:
            error_detalle = f"HTTP {resp.status_code}: {(resp.text or '')[:500]}"
            logger.warning("privada_sync: %s respondió %s para %s", url, resp.status_code, id_legacy)
        else:
            body = resp.json()
            resultado = body.get("resultado") or "ERROR"
            gestion_id = body.get("gestion_id")
            motivo = body.get("motivo")
            diff = body.get("diff")
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño, nunca rompe el alta/edición
        error_detalle = str(exc)
        logger.warning("privada_sync: fallo sincronizando %s (%s): %r", id_legacy, url, exc)

    await _upsert_vinculo(
        db, caso_tipo=caso_tipo, caso_id=caso_id, id_legacy=id_legacy,
        resultado=resultado, gestion_id=gestion_id, motivo=motivo,
    )
    db.add(VinculoPrivadaSyncLog(
        caso_tipo=caso_tipo, caso_id=caso_id, id_legacy=id_legacy,
        resultado=resultado, gestion_id=gestion_id, motivo=motivo,
        diff_json=diff, http_status=http_status, error_detalle=error_detalle,
    ))
    await db.flush()

    # Alertas al panel de notificaciones (ADR-019): gestión nueva creada, campos
    # corregidos en una gestión ya vinculada, o caso que queda pendiente de revisión
    # manual. Nunca por un ERROR transitorio (sería ruido).
    if resultado == "LINKED_NEW":
        await _notificar_creacion(
            db, caso_tipo=caso_tipo, caso_id=caso_id, localidad=localidad, departamento=departamento,
            gestion_id=gestion_id,
        )
    elif resultado == "LINKED_EXISTING" and diff:
        await _notificar_correccion(
            db, caso_tipo=caso_tipo, caso_id=caso_id, localidad=localidad, departamento=departamento,
            diff=diff,
        )
    elif resultado == "PENDING_REVIEW":
        await _notificar_pendiente_revision(
            db, caso_tipo=caso_tipo, caso_id=caso_id, localidad=localidad, departamento=departamento,
            motivo=motivo,
        )
