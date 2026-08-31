"""Tests para el módulo programas."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta
from app.mi_lugar.models import ProyectoML
from app.programas.service import seed_programas

BASE = "/api/v1/vivienda/programas"


@pytest.mark.asyncio
async def test_listar_programas_vacio(client: AsyncClient):
    r = await client.get(BASE)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_listar_programas_con_seed(client: AsyncClient, db_session: AsyncSession):
    await seed_programas(db_session)
    await db_session.flush()

    r = await client.get(BASE)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 4
    codigos = {p["codigo"] for p in data}
    assert codigos == {"CORDOBA_HOGAR", "MI_LUGAR", "CORDON_CUNETA", "LOTEOS"}


@pytest.mark.asyncio
async def test_get_programa_por_id(client: AsyncClient, db_session: AsyncSession):
    await seed_programas(db_session)
    await db_session.flush()

    lista = (await client.get(BASE)).json()
    programa_id = lista[0]["id"]

    r = await client.get(f"{BASE}/{programa_id}")
    assert r.status_code == 200
    assert r.json()["id"] == programa_id


@pytest.mark.asyncio
async def test_get_programa_inexistente(client: AsyncClient):
    r = await client.get(f"{BASE}/no-existe")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_estadisticas_programa_vacio(client: AsyncClient, db_session: AsyncSession):
    await seed_programas(db_session)
    await db_session.flush()

    lista = (await client.get(BASE)).json()
    programa_id = lista[0]["id"]

    r = await client.get(f"{BASE}/{programa_id}/estadisticas")
    assert r.status_code == 200
    data = r.json()
    assert data["total_expedientes"] == 0
    assert data["por_estado"] == {}


@pytest.mark.asyncio
async def test_lectura_denegada_a_invitado(client_invitado: AsyncClient):
    """Bug fix: un usuario Firebase válido pero no registrado en portal_usuarios
    (role='invitado') no debe poder leer el catálogo de programas — antes el
    endpoint solo exigía `get_current_user` sin `require_roles`, así que cualquier
    usuario autenticado (aunque no estuviera en el sistema) podía leerlo."""
    r = await client_invitado.get(BASE)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_lectura_permitida_a_consulta(client_consulta: AsyncClient):
    r = await client_consulta.get(BASE)
    assert r.status_code == 200


# ── Tablero de Programas — KPIs agregados CC/CH/ML (spec-checklist-tecnico-dgv §8/§9) ──

@pytest.fixture
async def _tablero_seed(db_session: AsyncSession) -> None:
    db_session.add_all([
        EstadoCordonCuneta(id=1, label="TC", bg="#000", text_color="#fff", orden=0),
        EstadoCordonCuneta(id=2, label="En Obra", bg="#000", text_color="#fff", orden=1),
        EstadoCordobaHogar(id=1, label="TC", bg="#000", text_color="#fff", orden=0),
    ])
    db_session.add_all([
        MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=1, municipio="A", expediente="E-1",
                              monto=100, ok_gob="SI", estado_general=1),
        MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=2, municipio="B", expediente=None,
                              monto=50, ok_gob="NO", estado_general=2),
        # borrada -> no cuenta
        MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=3, municipio="C", expediente="E-3",
                              monto=999, ok_gob="SI", estado_general=1,
                              deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ])
    db_session.add_all([
        LocalidadCordobaHogar(id=str(uuid.uuid4()), orden=1, localidad="L1", expediente="E-1",
                              monto=1000, cantidad_casas=40, ok_gob="SI", estado_general=1),
        LocalidadCordobaHogar(id=str(uuid.uuid4()), orden=2, localidad="L2", expediente=None,
                              monto=None, cantidad_casas=None, ok_gob="NO", estado_general=None),
    ])
    db_session.add_all([
        ProyectoML(id=str(uuid.uuid4()), tipo="exp", nombre="P1", localidad_nombre="X",
                   expediente="E-1", monto=200, lotes=10),
        ProyectoML(id=str(uuid.uuid4()), tipo="muni", nombre="P2", localidad_nombre="Y",
                   expediente=None, monto=None, lotes=5),
    ])
    await db_session.flush()


@pytest.mark.asyncio
async def test_tablero_kpis(client: AsyncClient, _tablero_seed: None):
    r = await client.get(f"{BASE}/tablero")
    assert r.status_code == 200
    data = r.json()

    assert data["cordon_cuneta"] == {
        "municipios": 2, "con_expediente": 1, "convenio_firmado": 1,
        "monto": 150.0, "en_obra": 1, "en_tc": 1,
    }
    assert data["cordoba_hogar"] == {
        "localidades": 2, "total_casas": 40, "con_ok_gob": 1,
        "con_expediente": 1, "monto": 1000.0, "en_tc": 1,
    }
    assert data["mi_lugar"] == {
        "total": 2, "exp": 1, "muni": 1, "prov": 0,
        "total_lotes": 15, "con_expediente": 1, "monto": 200.0,
    }


@pytest.mark.asyncio
async def test_tablero_no_lo_ensombrece_get_programa(client: AsyncClient):
    """`/programas/tablero` debe resolver al endpoint del tablero, no a
    `/programas/{programa_id}` con programa_id='tablero' (404)."""
    r = await client.get(f"{BASE}/tablero")
    assert r.status_code == 200
    assert "cordon_cuneta" in r.json()


@pytest.mark.asyncio
async def test_tablero_accesible_a_tecnico_dgv(client_tecnico_dgv: AsyncClient, _tablero_seed: None):
    r = await client_tecnico_dgv.get(f"{BASE}/tablero")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_tablero_denegado_a_invitado(client_invitado: AsyncClient):
    r = await client_invitado.get(f"{BASE}/tablero")
    assert r.status_code == 403
