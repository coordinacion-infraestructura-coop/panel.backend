"""Botón "Actualizar datos" del Tablero de Gobierno (spec-tablero-gobierno-actualizar.md).

Dispara ya los jobs de Cloud Scheduler que traen las fuentes del tablero, en vez de correr los
syncs dentro del pedido: tardan minutos y el gateway corta antes. Un pedido cada 15 minutos; cada
uno queda en `ext_gob_sync_log` como auditoría.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.config import settings
from app.gobierno.models import ExtGobSyncLog

logger = logging.getLogger(__name__)

FUENTE_LOG = "actualizacion_manual"
JOBS = ("sync-gob-localidades", "sync-gob-transferencias", "sync-atp-compromiso-gobernador", "sync-gralgob-atp-interno")
ESPERA = timedelta(minutes=15)


class ActualizacionReciente(Exception):
    def __init__(self, anterior: datetime):
        super().__init__("hubo otra actualización hace menos de 15 minutos")
        self.anterior = anterior


class ActualizacionDeshabilitada(Exception):
    pass


def _token() -> str:
    import google.auth
    from google.auth.transport.requests import Request

    credenciales, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credenciales.refresh(Request())
    return credenciales.token


async def _correr_job(client: httpx.AsyncClient, token: str, job: str) -> bool:
    url = (
        f"https://cloudscheduler.googleapis.com/v1/projects/{settings.gcp_project_id}"
        f"/locations/{settings.scheduler_location}/jobs/{job}:run"
    )
    try:
        resp = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json={})
    except Exception as exc:  # noqa: BLE001
        logger.warning("actualizar tablero: %s no se pudo disparar: %r", job, exc)
        return False
    if resp.status_code != 200:
        logger.warning("actualizar tablero: %s respondió %s", job, resp.status_code)
        return False
    return True


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def ultimo_pedido(db: AsyncSession) -> dict | None:
    """Para la barra del tablero: el botón sabe si hay una actualización en curso aunque se
    recargue la página."""
    log = (
        await db.execute(
            select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == FUENTE_LOG, ExtGobSyncLog.estado != "fallido")
            .order_by(ExtGobSyncLog.corrida_en.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if log is None:
        return None
    jobs = next((a for a in (log.anomalias or []) if a.get("tipo") == "jobs"), {})
    pedido = _utc(log.corrida_en)
    return {"pedido_en": pedido, "disparados": jobs.get("disparados", []), "fallidos": jobs.get("fallidos", []), "proxima_desde": pedido + ESPERA}


async def disparar(db: AsyncSession, usuario: AuthUser, ahora: datetime | None = None) -> dict:
    if not settings.actualizar_tablero_enabled:
        raise ActualizacionDeshabilitada("ACTUALIZAR_TABLERO_ENABLED está apagado")
    ahora = ahora or datetime.now(timezone.utc)
    anterior = (
        await db.execute(
            select(ExtGobSyncLog.corrida_en).where(ExtGobSyncLog.fuente == FUENTE_LOG, ExtGobSyncLog.estado != "fallido").order_by(ExtGobSyncLog.corrida_en.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if anterior is not None:
        anterior = _utc(anterior)
        if ahora - anterior < ESPERA:
            raise ActualizacionReciente(anterior)

    token = await asyncio.to_thread(_token)
    async with httpx.AsyncClient(timeout=20) as client:
        resultados = {job: await _correr_job(client, token, job) for job in JOBS}
    disparados = [j for j, ok in resultados.items() if ok]
    fallidos = [j for j, ok in resultados.items() if not ok]
    db.add(ExtGobSyncLog(
        fuente=FUENTE_LOG,
        estado="ok" if not fallidos else "parcial" if disparados else "fallido",
        anomalias=[{"tipo": "jobs", "disparados": disparados, "fallidos": fallidos}],
        corrida_en=ahora,
        disparado_por=usuario.email or usuario.uid,
        filas_leidas=0, filas_upsert=len(disparados), filas_error=len(fallidos), filas_sin_match=0,
    ))
    await db.flush()
    return {"disparados": disparados, "fallidos": fallidos, "pedido_en": ahora, "proxima_desde": ahora + ESPERA}
