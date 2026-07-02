"""Tests de integración para el módulo Cordón Cuneta."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordon_cuneta.models import (
    ConfigCordonCuneta,
    EstadoCordonCuneta,
    MunicipioCordonCuneta,
)

BASE = "/api/v1/vivienda/cordon-cuneta"
CONFIG_URL = "/api/v1/vivienda/cordon-cuneta-config/presupuesto"

_ESTADO_BASE = {"id": 1, "label": "Sin iniciar", "bg": "#eee", "text_color": "#000", "orden": 0}


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def estado(db_session: AsyncSession) -> int:
    db_session.add(EstadoCordonCuneta(**_ESTADO_BASE))
    await db_session.flush()
    return _ESTADO_BASE["id"]


@pytest_asyncio.fixture
async def municipio_id(db_session: AsyncSession, estado: int) -> str:
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid,
        orden=1,
        municipio="Córdoba Capital",
        departamento="Capital",
        ejuridico=estado,
        etecnico=estado,
        efinanciero=estado,
    ))
    await db_session.flush()
    return mid


@pytest_asyncio.fixture
async def config(db_session: AsyncSession) -> None:
    db_session.add(ConfigCordonCuneta(id=1, presupuesto=0))
    await db_session.flush()


# ── GET panel ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_full_devuelve_estructura(client: AsyncClient, municipio_id: str, config: None):
    r = await client.get(BASE)
    assert r.status_code == 200
    data = r.json()
    assert "municipios" in data
    assert "estados" in data
    assert "presupuesto" in data
    assert len(data["municipios"]) == 1
    assert data["municipios"][0]["municipio"] == "Córdoba Capital"


@pytest.mark.asyncio
async def test_get_full_sin_datos(client: AsyncClient):
    r = await client.get(BASE)
    assert r.status_code == 200
    assert r.json()["municipios"] == []


@pytest.mark.asyncio
async def test_listar_estados(client: AsyncClient, estado: int):
    r = await client.get(f"{BASE}/estados")
    assert r.status_code == 200
    assert len(r.json()) == 1


# ── PATCH municipio ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_municipio(client: AsyncClient, municipio_id: str):
    r = await client.patch(f"{BASE}/{municipio_id}", json={"expediente": "EXP-CC-001"})
    assert r.status_code == 200
    assert r.json()["expediente"] == "EXP-CC-001"


@pytest.mark.asyncio
async def test_actualizar_municipio_inexistente(client: AsyncClient):
    r = await client.patch(f"{BASE}/{uuid.uuid4()}", json={"obs": "Test"})
    assert r.status_code == 404


# ── Presupuesto ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_presupuesto(client: AsyncClient):
    r = await client.patch(CONFIG_URL, json={"presupuesto": "8000000.00"})
    assert r.status_code == 200
    assert r.json()["presupuesto"] == 8000000.0


@pytest.mark.asyncio
async def test_actualizar_presupuesto_existente(client: AsyncClient, config: None):
    await client.patch(CONFIG_URL, json={"presupuesto": "1000000.00"})
    r = await client.patch(CONFIG_URL, json={"presupuesto": "3000000.00"})
    assert r.json()["presupuesto"] == 3000000.0


# ── Pedidos ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_pedidos_municipio_inexistente_devuelve_404(client: AsyncClient):
    """Bug 4 fix: debe retornar 404, no lista vacía."""
    r = await client.get(f"{BASE}/{uuid.uuid4()}/pedidos")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "RECURSO_NO_ENCONTRADO"


@pytest.mark.asyncio
async def test_listar_pedidos_vacio(client: AsyncClient, municipio_id: str):
    r = await client.get(f"{BASE}/{municipio_id}/pedidos")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_crear_pedido(client: AsyncClient, municipio_id: str):
    r = await client.post(f"{BASE}/{municipio_id}/pedidos", json={
        "descripcion": "Nota de avance",
        "fecha_pedido": "2026-06-15",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["descripcion"] == "Nota de avance"
    assert data["municipio_id"] == municipio_id


@pytest.mark.asyncio
async def test_crear_pedido_municipio_inexistente(client: AsyncClient):
    r = await client.post(f"{BASE}/{uuid.uuid4()}/pedidos", json={
        "descripcion": "X",
        "fecha_pedido": "2026-06-15",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_eliminar_pedido(client: AsyncClient, municipio_id: str):
    cr = await client.post(f"{BASE}/{municipio_id}/pedidos", json={
        "descripcion": "Borrar",
        "fecha_pedido": "2026-06-15",
    })
    pedido_id = cr.json()["id"]

    r = await client.delete(f"{BASE}/{municipio_id}/pedidos/{pedido_id}")
    assert r.status_code == 204

    r2 = await client.get(f"{BASE}/{municipio_id}/pedidos")
    assert r2.json() == []


@pytest.mark.asyncio
async def test_eliminar_pedido_inexistente(client: AsyncClient, municipio_id: str):
    r = await client.delete(f"{BASE}/{municipio_id}/pedidos/{uuid.uuid4()}")
    assert r.status_code == 404


# ── Control de acceso ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lectura_permitida_a_consulta(client_consulta: AsyncClient, municipio_id: str):
    r = await client_consulta.get(BASE)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_creacion_pedido_denegada_a_consulta(client_consulta: AsyncClient, municipio_id: str):
    r = await client_consulta.post(f"{BASE}/{municipio_id}/pedidos", json={
        "descripcion": "No permitido",
        "fecha_pedido": "2026-06-15",
    })
    assert r.status_code == 403
