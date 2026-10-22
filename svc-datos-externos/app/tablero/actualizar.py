"""Botón "Actualizar datos" del Tablero de Gobierno (spec-tablero-gobierno-actualizar.md).

Dispara ya los jobs de Cloud Scheduler que traen las fuentes del tablero, en vez de correr los
syncs dentro del pedido: tardan y el gateway corta antes. Cada pedido queda en `ext_gob_sync_log`
como auditoría. El pedido se da por terminado cuando los syncs de este servicio registraron una
corrida posterior (`ultimo_pedido`); mientras tanto no se acepta otro, hasta 15 minutos.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.config import settings
from app.fuentes_oficiales.models import ExtFuentesOficialesSyncLog
from app.fuentes_oficiales.sync import FUENTES as FUENTES_OFICIALES
from app.gob_transferencias.sync import FUENTES as FUENTES_PLANILLAS
from app.gobierno.models import ExtGobSyncLog
from app.gobierno.sync import FUENTE_NOMENCLADOR

logger = logging.getLogger(__name__)

FUENTE_LOG = "actualizacion_manual"
JOBS = (
    "sync-gob-localidades",
    "sync-gob-transferencias",
    "sync-transferencias-transparencia",
    "sync-fuentes-oficiales",
    "sync-atp-compromiso-gobernador",
    "sync-gralgob-atp-interno",
)
ESPERA = timedelta(minutes=15)

# Cómo se sabe que terminó cada job de este servicio: la última fuente que registra. Transparencia
# (salvo un mes nuevo) y los dos de ATP (svc-gralgob) terminan en segundos y no se esperan.
_ULTIMA_PLANILLA = list(FUENTES_PLANILLAS)[-1]
_ULTIMA_OFICIAL = FUENTES_OFICIALES[-1]


class ActualizacionReciente(Exception):
    def __init__(self, anterior: datetime):
        super().__init__("hay una actualización en curso")
        self.anterior = anterior


class ActualizacionDeshabilitada(Exception):
    pass


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


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


async def _terminado_en(db: AsyncSession, pedido: datetime, disparados: list[str]) -> datetime | None:
    """Hora en que terminó el último de los jobs que se esperan, o None si alguno sigue."""
    consultas = {
        "sync-gob-localidades": select(func.max(ExtGobSyncLog.corrida_en)).where(ExtGobSyncLog.fuente == FUENTE_NOMENCLADOR),
        "sync-gob-transferencias": select(func.max(ExtGobSyncLog.corrida_en)).where(ExtGobSyncLog.fuente == _ULTIMA_PLANILLA),
        "sync-fuentes-oficiales": select(func.max(ExtFuentesOficialesSyncLog.finalizado_at)).where(
            ExtFuentesOficialesSyncLog.fuente == _ULTIMA_OFICIAL
        ),
    }
    fines: list[datetime] = []
    for job, consulta in consultas.items():
        if job not in disparados:
            continue
        fin = (await db.execute(consulta)).scalar_one_or_none()
        if fin is None or _utc(fin) < pedido:
            return None
        fines.append(_utc(fin))
    return max(fines, default=pedido)


async def ultimo_pedido(db: AsyncSession, ahora: datetime | None = None) -> dict | None:
    """Para la barra del tablero: el botón sabe si hay una actualización en curso aunque se
    recargue la página, y cuándo terminó."""
    log = (
        await db.execute(
            select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == FUENTE_LOG, ExtGobSyncLog.estado != "fallido")
            .order_by(ExtGobSyncLog.corrida_en.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if log is None:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    jobs = next((a for a in (log.anomalias or []) if a.get("tipo") == "jobs"), {})
    pedido = _utc(log.corrida_en)
    disparados = jobs.get("disparados", [])
    terminado = await _terminado_en(db, pedido, disparados)
    return {
        "pedido_en": pedido,
        "disparados": disparados,
        "fallidos": jobs.get("fallidos", []),
        "terminado_en": terminado,
        "en_curso": terminado is None and ahora - pedido < ESPERA,
        "proxima_desde": pedido + ESPERA,
    }


async def disparar(db: AsyncSession, usuario: AuthUser, ahora: datetime | None = None) -> dict:
    if not settings.actualizar_tablero_enabled:
        raise ActualizacionDeshabilitada("ACTUALIZAR_TABLERO_ENABLED está apagado")
    ahora = ahora or datetime.now(timezone.utc)
    anterior = await ultimo_pedido(db, ahora)
    if anterior and anterior["en_curso"]:
        raise ActualizacionReciente(anterior["pedido_en"])

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
    return {
        "pedido_en": ahora, "disparados": disparados, "fallidos": fallidos,
        "terminado_en": None, "en_curso": bool(disparados), "proxima_desde": ahora + ESPERA,
    }
