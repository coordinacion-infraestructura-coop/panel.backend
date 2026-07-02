"""Tests de integración para el módulo Córdoba Hogar."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import ConfigCordobaHogar, EstadoCordobaHogar, LocalidadCordobaHogar

BASE = "/api/v1/vivienda/cordoba-hogar"
CONFIG_URL = "/api/v1/vivienda/cordoba-hogar-config/presupuesto"

_ESTADO_BASE = {"id": 1, "label": "Sin iniciar", "bg": "#ccc", "text_color": "#000", "orden": 0}


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def estado(db_session: AsyncSession) -> int:
    """Inserta un estado de referencia y retorna su id."""
    db_session.add(EstadoCordobaHogar(**_ESTADO_BASE))
    await db_session.flush()
    return _ESTADO_BASE["id"]


@pytest_asyncio.fixture
async def localidad_id(db_session: AsyncSession, estado: int) -> str:
    lid = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid,
        orden=1,
        localidad="Villa Carlos Paz",
        departamento="Punilla",
        ejuridico=estado,
        etecnico=estado,
        efinanciero=estado,
    ))
    await db_session.flush()
    return lid


@pytest_asyncio.fixture
async def config(db_session: AsyncSession) -> None:
    db_session.add(ConfigCordobaHogar(id=1, presupuesto=0))
    await db_session.flush()


# ── GET panel completo ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_full_devuelve_estructura(client: AsyncClient, localidad_id: str, config: None):
    r = await client.get(BASE)
    assert r.status_code == 200
    data = r.json()
    assert "localidades" in data
    assert "estados" in data
    assert "presupuesto" in data
    assert len(data["localidades"]) == 1
    assert data["localidades"][0]["localidad"] == "Villa Carlos Paz"


@pytest.mark.asyncio
async def test_get_full_sin_datos_devuelve_vacios(client: AsyncClient):
    r = await client.get(BASE)
    assert r.status_code == 200
    data = r.json()
    assert data["localidades"] == []
    assert data["presupuesto"] == 0.0


@pytest.mark.asyncio
async def test_listar_estados(client: AsyncClient, estado: int):
    r = await client.get(f"{BASE}/estados")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["label"] == "Sin iniciar"


# ── PATCH localidad ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_localidad(client: AsyncClient, localidad_id: str):
    r = await client.patch(f"{BASE}/{localidad_id}", json={"expediente": "EXP-2026-001"})
    assert r.status_code == 200
    assert r.json()["expediente"] == "EXP-2026-001"


@pytest.mark.asyncio
async def test_actualizar_localidad_inexistente(client: AsyncClient):
    r = await client.patch(f"{BASE}/{uuid.uuid4()}", json={"expediente": "X"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_actualizar_localidad_requiere_escritura(client_consulta: AsyncClient, localidad_id: str):
    r = await client_consulta.patch(f"{BASE}/{localidad_id}", json={"obs": "Nota"})
    assert r.status_code == 403


# ── Presupuesto ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_presupuesto_crea_si_no_existe(client: AsyncClient):
    r = await client.patch(CONFIG_URL, json={"presupuesto": "5000000.00"})
    assert r.status_code == 200
    assert r.json()["presupuesto"] == 5000000.0


@pytest.mark.asyncio
async def test_actualizar_presupuesto_actualiza_existente(client: AsyncClient, config: None):
    await client.patch(CONFIG_URL, json={"presupuesto": "1000000.00"})
    r = await client.patch(CONFIG_URL, json={"presupuesto": "2000000.00"})
    assert r.status_code == 200
    assert r.json()["presupuesto"] == 2000000.0


# ── Pedidos ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_pedidos_localidad_inexistente_devuelve_404(client: AsyncClient):
    """Bug 3 fix: debe retornar 404, no lista vacía."""
    r = await client.get(f"{BASE}/{uuid.uuid4()}/pedidos")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "RECURSO_NO_ENCONTRADO"


@pytest.mark.asyncio
async def test_listar_pedidos_vacio(client: AsyncClient, localidad_id: str):
    r = await client.get(f"{BASE}/{localidad_id}/pedidos")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_crear_pedido(client: AsyncClient, localidad_id: str):
    r = await client.post(f"{BASE}/{localidad_id}/pedidos", json={
        "descripcion": "Solicitud de documentación",
        "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["descripcion"] == "Solicitud de documentación"
    assert data["localidad_id"] == localidad_id
    assert "id" in data


@pytest.mark.asyncio
async def test_crear_pedido_localidad_inexistente(client: AsyncClient):
    r = await client.post(f"{BASE}/{uuid.uuid4()}/pedidos", json={
        "descripcion": "X",
        "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_listar_pedidos_devuelve_creados(client: AsyncClient, localidad_id: str):
    await client.post(f"{BASE}/{localidad_id}/pedidos", json={
        "descripcion": "Pedido 1",
        "fecha_pedido": "2026-07-01",
    })
    await client.post(f"{BASE}/{localidad_id}/pedidos", json={
        "descripcion": "Pedido 2",
        "fecha_pedido": "2026-07-02",
    })
    r = await client.get(f"{BASE}/{localidad_id}/pedidos")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_eliminar_pedido(client: AsyncClient, localidad_id: str):
    cr = await client.post(f"{BASE}/{localidad_id}/pedidos", json={
        "descripcion": "Temporal",
        "fecha_pedido": "2026-07-01",
    })
    pedido_id = cr.json()["id"]

    r = await client.delete(f"{BASE}/{localidad_id}/pedidos/{pedido_id}")
    assert r.status_code == 204

    r2 = await client.get(f"{BASE}/{localidad_id}/pedidos")
    assert r2.json() == []


@pytest.mark.asyncio
async def test_eliminar_pedido_inexistente(client: AsyncClient, localidad_id: str):
    r = await client.delete(f"{BASE}/{localidad_id}/pedidos/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pedidos_aislados_por_localidad(client: AsyncClient, db_session: AsyncSession, estado: int):
    """Pedidos de una localidad no aparecen en otra."""
    lid2 = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid2, orden=2, localidad="Jesús María",
        ejuridico=estado, etecnico=estado, efinanciero=estado,
    ))
    await db_session.flush()

    lid1 = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid1, orden=3, localidad="Alta Gracia",
        ejuridico=estado, etecnico=estado, efinanciero=estado,
    ))
    await db_session.flush()

    await client.post(f"{BASE}/{lid1}/pedidos", json={"descripcion": "X", "fecha_pedido": "2026-07-01"})

    r = await client.get(f"{BASE}/{lid2}/pedidos")
    assert r.json() == []
