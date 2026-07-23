"""Tests de integración para el módulo Córdoba Hogar."""
import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import (
    ConfigCordobaHogar,
    EstadoCordobaHogar,
    LocalidadCordobaHogar,
    PedidoCordobaHogar,
)

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


@pytest_asyncio.fixture
async def dos_estados(db_session: AsyncSession) -> tuple[int, int]:
    """Dos estados con ordenes distintos para simular una transición."""
    id_a, id_b = 100, 200
    db_session.add(EstadoCordobaHogar(
        id=id_a, label="En proceso", bg="#ffe", text_color="#333", orden=10,
    ))
    db_session.add(EstadoCordobaHogar(
        id=id_b, label="Completado", bg="#dfd", text_color="#060", orden=20,
    ))
    await db_session.flush()
    return id_a, id_b


@pytest_asyncio.fixture
async def localidad_con_estado(
    db_session: AsyncSession, dos_estados: tuple[int, int]
) -> tuple[str, int, int]:
    """Localidad con todos los campos de estado en id_a. Retorna (localidad_id, id_a, id_b)."""
    id_a, id_b = dos_estados
    lid = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid, orden=99, localidad="Pueblo Test", departamento="Test",
        ejuridico=id_a, etecnico=id_a, efinanciero=id_a, estado_general=id_a,
    ))
    await db_session.flush()
    return lid, id_a, id_b


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


# ── Asignación de secretaría en crear_pedido ──────────────────────────────────

@pytest.mark.asyncio
async def test_crear_pedido_asigna_secretaria_supervision_con_prioridad(
    client_supervision: AsyncClient, localidad_id: str
):
    r = await client_supervision.post(f"{BASE}/{localidad_id}/pedidos", json={
        "descripcion": "Nota", "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 201
    assert r.json()["secretaria"] == "supervision"


@pytest.mark.asyncio
async def test_crear_pedido_asigna_secretaria_infraestructura(
    client_infraestructura: AsyncClient, localidad_id: str
):
    r = await client_infraestructura.post(f"{BASE}/{localidad_id}/pedidos", json={
        "descripcion": "Nota", "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 201
    assert r.json()["secretaria"] == "infraestructura"


@pytest.mark.asyncio
async def test_crear_pedido_asigna_primera_secretaria_del_actor(
    client_operador: AsyncClient, localidad_id: str
):
    """OPERADOR_USER tiene secretarias=['vivienda'] — sin infraestructura/supervision,
    se asigna la primera secretaría del actor."""
    r = await client_operador.post(f"{BASE}/{localidad_id}/pedidos", json={
        "descripcion": "Nota", "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 201
    assert r.json()["secretaria"] == "vivienda"


# ── Visibilidad jerárquica de pedidos por secretaría ──────────────────────────

@pytest_asyncio.fixture
async def pedidos_multi_secretaria(db_session: AsyncSession, localidad_id: str) -> str:
    """Un pedido de cada secretaría (None ~ vivienda, infraestructura, supervision)."""
    for sec, desc in [(None, "Pedido vivienda"), ("infraestructura", "Pedido infra"), ("supervision", "Pedido superv")]:
        db_session.add(PedidoCordobaHogar(
            localidad_id=localidad_id, descripcion=desc, fecha_pedido=date(2026, 7, 1), secretaria=sec,
        ))
    await db_session.flush()
    return localidad_id


@pytest.mark.asyncio
async def test_listar_pedidos_vivienda_no_ve_infraestructura_ni_supervision(
    client_operador: AsyncClient, pedidos_multi_secretaria: str
):
    r = await client_operador.get(f"{BASE}/{pedidos_multi_secretaria}/pedidos")
    assert {p["descripcion"] for p in r.json()} == {"Pedido vivienda"}


@pytest.mark.asyncio
async def test_listar_pedidos_infraestructura_ve_vivienda_y_propia_no_supervision(
    client_infraestructura: AsyncClient, pedidos_multi_secretaria: str
):
    r = await client_infraestructura.get(f"{BASE}/{pedidos_multi_secretaria}/pedidos")
    assert {p["descripcion"] for p in r.json()} == {"Pedido vivienda", "Pedido infra"}


@pytest.mark.asyncio
async def test_listar_pedidos_supervision_ve_todo(
    client_supervision: AsyncClient, pedidos_multi_secretaria: str
):
    r = await client_supervision.get(f"{BASE}/{pedidos_multi_secretaria}/pedidos")
    assert {p["descripcion"] for p in r.json()} == {"Pedido vivienda", "Pedido infra", "Pedido superv"}


@pytest.mark.asyncio
async def test_listar_pedidos_admin_ve_todo(client: AsyncClient, pedidos_multi_secretaria: str):
    r = await client.get(f"{BASE}/{pedidos_multi_secretaria}/pedidos")
    assert len(r.json()) == 3


# ── estado_general ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_estado_general_se_recomputa_al_cambiar_dimension(
    client: AsyncClient, localidad_con_estado: tuple
):
    """Paridad con Cordón Cuneta: estado_general siempre refleja el estado con
    menor orden entre los tres campos (cuando el PATCH es parcial)."""
    lid, id_a, id_b = localidad_con_estado
    r = await client.patch(f"{BASE}/{lid}", json={"ejuridico": id_b})
    assert r.json()["estado_general"] == id_a

    r2 = await client.patch(f"{BASE}/{lid}", json={"etecnico": id_b, "efinanciero": id_b})
    assert r2.json()["estado_general"] == id_b


@pytest.mark.asyncio
async def test_reordenar_estado_recomputa_estado_general_de_localidades(
    client: AsyncClient, db_session: AsyncSession, dos_estados: tuple[int, int]
):
    """Cambiar el `orden` de un estado del catálogo debe recalcular retroactivamente
    el estado_general de todas las localidades que lo usan (bug: antes quedaba
    desactualizado hasta el próximo cambio manual de dimensión)."""
    id_a, id_b = dos_estados  # id_a: orden=10, id_b: orden=20
    lid = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid, orden=1, localidad="Pueblo Mixto", departamento="Test",
        ejuridico=id_a, etecnico=id_b, efinanciero=id_a, estado_general=id_a,
    ))
    await db_session.flush()

    r0 = await client.get(BASE)
    localidad0 = next(l for l in r0.json()["localidades"] if l["id"] == lid)
    assert localidad0["estado_general"] == id_a

    # Reordenamos id_a para que quede DESPUÉS de id_b — ahora el mínimo pasa a ser id_b.
    r = await client.patch(f"{BASE}/estados/{id_a}", json={"orden": 999})
    assert r.status_code == 200

    r2 = await client.get(BASE)
    localidad2 = next(l for l in r2.json()["localidades"] if l["id"] == lid)
    assert localidad2["estado_general"] == id_b


# ── Creación de localidades ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_localidad(client: AsyncClient):
    r = await client.post(BASE, json={"localidad": "Villa Nueva", "departamento": "Colón"})
    assert r.status_code == 201
    data = r.json()
    assert data["localidad"] == "Villa Nueva"
    assert data["departamento"] == "Colón"


@pytest.mark.asyncio
async def test_crear_localidad_duplicada_devuelve_409(client: AsyncClient):
    await client.post(BASE, json={"localidad": "Villa Nueva", "departamento": "Colón"})
    r = await client.post(BASE, json={"localidad": "villa nueva", "departamento": "COLÓN"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "LOCALIDAD_DUPLICADA"
    assert "existing_id" in r.json()["detail"]
