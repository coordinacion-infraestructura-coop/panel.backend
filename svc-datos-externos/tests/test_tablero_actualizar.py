"""Botón "Actualizar datos" del tablero (spec-tablero-gobierno-actualizar.md §3)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from httpx import AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gobierno.models import ExtGobSyncLog
from app.tablero import actualizar
from tests.conftest import CONSULTA_USER

URL = "/api/v1/datos-externos/tablero/actualizar"


@pytest.fixture(autouse=True)
def scheduler(monkeypatch):
    monkeypatch.setattr(settings, "actualizar_tablero_enabled", True)
    monkeypatch.setattr(actualizar, "_token", lambda: "token")
    corrida = AsyncMock(return_value=True)
    monkeypatch.setattr(actualizar, "_correr_job", corrida)
    return corrida


async def test_dispara_los_jobs_y_deja_registro(client: AsyncClient, db_session: AsyncSession, scheduler):
    r = await client.post(URL)
    assert r.status_code == 200, r.text
    assert r.json()["disparados"] == list(actualizar.JOBS) and r.json()["fallidos"] == []
    assert [c.args[2] for c in scheduler.await_args_list] == list(actualizar.JOBS)
    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == actualizar.FUENTE_LOG))).scalar_one()
    assert log.estado == "ok" and log.disparado_por

    # Segundo pedido enseguida: 409.
    r = await client.post(URL)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ACTUALIZACION_RECIENTE"


async def test_pasados_15_minutos_se_puede_de_nuevo(client: AsyncClient, db_session: AsyncSession):
    db_session.add(ExtGobSyncLog(fuente=actualizar.FUENTE_LOG, estado="ok", corrida_en=datetime.now(timezone.utc) - timedelta(minutes=16),
                                 disparado_por="x", filas_leidas=0, filas_upsert=4, filas_error=0, filas_sin_match=0))
    await db_session.commit()
    assert (await client.post(URL)).status_code == 200


async def test_si_fallan_todos_no_bloquea_el_siguiente(client: AsyncClient, scheduler):
    scheduler.return_value = False
    r = await client.post(URL)
    assert r.status_code == 200 and r.json()["disparados"] == []
    scheduler.return_value = True
    assert (await client.post(URL)).status_code == 200


async def test_apagado_y_roles(client: AsyncClient, as_user, monkeypatch):
    monkeypatch.setattr(settings, "actualizar_tablero_enabled", False)
    assert (await client.post(URL)).status_code == 503
    as_user(CONSULTA_USER)
    assert (await client.post(URL)).status_code == 403


async def test_meta_informa_el_ultimo_pedido(client: AsyncClient):
    assert (await client.get("/api/v1/datos-externos/tablero/meta")).json()["actualizacion"] is None
    await client.post(URL)
    a = (await client.get("/api/v1/datos-externos/tablero/meta")).json()["actualizacion"]
    assert a["disparados"] == list(actualizar.JOBS) and a["proxima_desde"] > a["pedido_en"]


def test_cliente_de_sheets_uno_por_hilo(monkeypatch):
    import threading

    from app.integrations import google_sheets

    monkeypatch.setattr(google_sheets.google.auth, "default", lambda scopes: (object(), None))
    monkeypatch.setattr(google_sheets, "build", lambda *a, **k: object())
    google_sheets._local.__dict__.clear()
    vistos = []
    hilos = [threading.Thread(target=lambda: vistos.append(google_sheets._get_service())) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert vistos[0] is not vistos[1]
    assert google_sheets._get_service() is google_sheets._get_service()
