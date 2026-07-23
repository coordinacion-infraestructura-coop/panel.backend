"""Tests de integración para el módulo Cordón Cuneta."""
import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordon_cuneta.models import (
    ConfigCordonCuneta,
    EstadoCordonCuneta,
    EstadoHistorialCC,
    MunicipioCordonCuneta,
    PedidoCordonCuneta,
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


# ── Asignación de secretaría en crear_pedido ──────────────────────────────────

@pytest.mark.asyncio
async def test_crear_pedido_asigna_secretaria_supervision_con_prioridad(
    client_supervision: AsyncClient, municipio_id: str
):
    r = await client_supervision.post(f"{BASE}/{municipio_id}/pedidos", json={
        "descripcion": "Nota", "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 201
    assert r.json()["secretaria"] == "supervision"


@pytest.mark.asyncio
async def test_crear_pedido_asigna_secretaria_infraestructura(
    client_infraestructura: AsyncClient, municipio_id: str
):
    r = await client_infraestructura.post(f"{BASE}/{municipio_id}/pedidos", json={
        "descripcion": "Nota", "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 201
    assert r.json()["secretaria"] == "infraestructura"


@pytest.mark.asyncio
async def test_crear_pedido_asigna_primera_secretaria_del_actor(
    client_operador: AsyncClient, municipio_id: str
):
    """OPERADOR_USER tiene secretarias=['vivienda'] — sin infraestructura/supervision,
    se asigna la primera secretaría del actor."""
    r = await client_operador.post(f"{BASE}/{municipio_id}/pedidos", json={
        "descripcion": "Nota", "fecha_pedido": "2026-07-01",
    })
    assert r.status_code == 201
    assert r.json()["secretaria"] == "vivienda"


# ── Visibilidad jerárquica de pedidos por secretaría ──────────────────────────

@pytest_asyncio.fixture
async def pedidos_multi_secretaria(db_session: AsyncSession, municipio_id: str) -> str:
    """Un pedido de cada secretaría (None ~ vivienda, infraestructura, supervision)."""
    for sec, desc in [(None, "Pedido vivienda"), ("infraestructura", "Pedido infra"), ("supervision", "Pedido superv")]:
        db_session.add(PedidoCordonCuneta(
            municipio_id=municipio_id, descripcion=desc, fecha_pedido=date(2026, 7, 1), secretaria=sec,
        ))
    await db_session.flush()
    return municipio_id


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


# ── Fixtures para tests de historial ──────────────────────────────────────────

@pytest_asyncio.fixture
async def dos_estados(db_session: AsyncSession) -> tuple[int, int]:
    """Dos estados con ordenes distintos para simular una transición."""
    id_a, id_b = 100, 200
    db_session.add(EstadoCordonCuneta(
        id=id_a, label="En proceso", bg="#ffe", text_color="#333", orden=10,
    ))
    db_session.add(EstadoCordonCuneta(
        id=id_b, label="Completado",  bg="#dfd", text_color="#060", orden=20,
    ))
    await db_session.flush()
    return id_a, id_b


@pytest_asyncio.fixture
async def municipio_con_estado(
    db_session: AsyncSession, dos_estados: tuple[int, int]
) -> tuple[str, int, int]:
    """Municipio con todos los campos de estado en id_a. Retorna (municipio_id, id_a, id_b)."""
    id_a, id_b = dos_estados
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid,
        orden=99,
        municipio="Pueblo Test",
        departamento="Test",
        ejuridico=id_a,
        etecnico=id_a,
        efinanciero=id_a,
        estado_general=id_a,
    ))
    await db_session.flush()
    return mid, id_a, id_b


# ── Historial de cambios de estado ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cambio_estado_crea_entrada_historial(
    client: AsyncClient, municipio_con_estado: tuple
):
    """PATCH de un campo de estado genera exactamente una entrada en historial."""
    mid, id_a, id_b = municipio_con_estado
    r = await client.patch(f"{BASE}/{mid}", json={"ejuridico": id_b})
    assert r.status_code == 200

    hist = (await client.get(f"{BASE}/{mid}/historial")).json()
    assert len(hist) == 1
    assert hist[0]["campo"] == "ejuridico"


@pytest.mark.asyncio
async def test_cambio_estado_registra_anterior_nuevo_y_actor(
    client: AsyncClient, municipio_con_estado: tuple
):
    """La entrada registra estado_anterior, estado_nuevo y el email del actor."""
    mid, id_a, id_b = municipio_con_estado
    await client.patch(f"{BASE}/{mid}", json={"etecnico": id_b})

    entry = (await client.get(f"{BASE}/{mid}/historial")).json()[0]
    assert entry["campo"] == "etecnico"
    assert entry["estado_anterior_id"] == id_a
    assert entry["estado_nuevo_id"] == id_b
    assert entry["created_by"] == "admin@test.com"


@pytest.mark.asyncio
async def test_mismo_estado_no_genera_historial(
    client: AsyncClient, municipio_con_estado: tuple
):
    """Si el estado enviado es igual al actual no debe generarse ninguna entrada."""
    mid, id_a, _ = municipio_con_estado
    await client.patch(f"{BASE}/{mid}", json={"ejuridico": id_a})

    hist = (await client.get(f"{BASE}/{mid}/historial")).json()
    assert hist == []


@pytest.mark.asyncio
async def test_multiples_campos_generan_multiples_entradas(
    client: AsyncClient, municipio_con_estado: tuple
):
    """Cambiar ejuridico + etecnico en un solo PATCH produce dos entradas."""
    mid, id_a, id_b = municipio_con_estado
    r = await client.patch(f"{BASE}/{mid}", json={"ejuridico": id_b, "etecnico": id_b})
    assert r.status_code == 200

    hist = (await client.get(f"{BASE}/{mid}/historial")).json()
    assert len(hist) == 2
    assert {e["campo"] for e in hist} == {"ejuridico", "etecnico"}


@pytest.mark.asyncio
async def test_historial_retorna_entradas_mas_recientes_primero(
    client: AsyncClient, municipio_con_estado: tuple
):
    """El endpoint /historial ordena de más reciente a más antiguo."""
    mid, id_a, id_b = municipio_con_estado
    await client.patch(f"{BASE}/{mid}", json={"ejuridico": id_b})
    await client.patch(f"{BASE}/{mid}", json={"etecnico": id_b})

    hist = (await client.get(f"{BASE}/{mid}/historial")).json()
    assert len(hist) == 2
    assert hist[0]["campo"] == "etecnico"   # segundo cambio → primero en la lista
    assert hist[1]["campo"] == "ejuridico"


@pytest.mark.asyncio
async def test_historial_vacio_para_municipio_sin_cambios(
    client: AsyncClient, municipio_con_estado: tuple
):
    """Un municipio recién creado sin cambios de estado devuelve lista vacía."""
    mid, _, _ = municipio_con_estado
    r = await client.get(f"{BASE}/{mid}/historial")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_estado_general_se_recomputa_al_cambiar_dimension(
    client: AsyncClient, municipio_con_estado: tuple
):
    """estado_general siempre refleja el estado con menor orden entre los tres campos."""
    mid, id_a, id_b = municipio_con_estado
    # Solo ejuridico cambia a id_b (orden 20). etecnico y efinanciero quedan en id_a (orden 10).
    # estado_general debe seguir siendo id_a.
    r = await client.patch(f"{BASE}/{mid}", json={"ejuridico": id_b})
    assert r.json()["estado_general"] == id_a

    # Ahora todos pasan a id_b → estado_general debe ser id_b.
    r2 = await client.patch(f"{BASE}/{mid}", json={"etecnico": id_b, "efinanciero": id_b})
    assert r2.json()["estado_general"] == id_b


@pytest.mark.asyncio
async def test_reordenar_estado_recomputa_estado_general_de_municipios(
    client: AsyncClient, db_session: AsyncSession, dos_estados: tuple[int, int]
):
    """Cambiar el `orden` de un estado del catálogo debe recalcular retroactivamente
    el estado_general de todos los municipios que lo usan (bug: antes quedaba
    desactualizado hasta el próximo cambio manual de dimensión)."""
    id_a, id_b = dos_estados  # id_a: orden=10, id_b: orden=20
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid, orden=1, municipio="Pueblo Mixto", departamento="Test",
        ejuridico=id_a, etecnico=id_b, efinanciero=id_a, estado_general=id_a,
    ))
    await db_session.flush()

    r0 = await client.get(BASE)
    municipio0 = next(m for m in r0.json()["municipios"] if m["id"] == mid)
    assert municipio0["estado_general"] == id_a

    # Reordenamos id_a para que quede DESPUÉS de id_b — ahora el mínimo pasa a ser id_b.
    r = await client.patch(f"{BASE}/estados/{id_a}", json={"orden": 999})
    assert r.status_code == 200

    r2 = await client.get(BASE)
    municipio2 = next(m for m in r2.json()["municipios"] if m["id"] == mid)
    assert municipio2["estado_general"] == id_b


# ── Creación de municipios ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_municipio(client: AsyncClient):
    r = await client.post(BASE, json={"municipio": "Villa Nueva", "departamento": "Colón"})
    assert r.status_code == 201
    data = r.json()
    assert data["municipio"] == "Villa Nueva"
    assert data["departamento"] == "Colón"


@pytest.mark.asyncio
async def test_crear_municipio_duplicado_devuelve_409(client: AsyncClient):
    await client.post(BASE, json={"municipio": "Villa Nueva", "departamento": "Colón"})
    r = await client.post(BASE, json={"municipio": "villa nueva", "departamento": "COLÓN"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "MUNICIPIO_DUPLICADO"
    assert "existing_id" in r.json()["detail"]
