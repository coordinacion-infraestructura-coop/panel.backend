"""Tests para el módulo programas."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
