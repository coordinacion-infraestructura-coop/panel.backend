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


# NOTA: `estado_general` es 100% manual desde 2026-07-31 (ver CLAUDE.md). El recálculo
# automático al cambiar una sub-dimensión o al reordenar el catálogo de estados fue
# removido a propósito porque pisaba overrides manuales — los tests que lo verificaban
# se eliminaron acá (paridad con test_cordon_cuneta.py).


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


# ── Resolución de localidad_id (ADR-024) ─────────────────────────────────────

@pytest_asyncio.fixture
async def geo_san_jose(db_session: AsyncSession):
    from app.geo.models import GeoLocalidad
    db_session.add(GeoLocalidad(id_geo="777", departamento="Tulumba", localidad="San José", activo=True))
    await db_session.flush()


@pytest.mark.asyncio
async def test_crear_localidad_resuelve_localidad_id(client: AsyncClient, geo_san_jose):
    r = await client.post(BASE, json={"localidad": "San José", "departamento": "Tulumba"})
    assert r.status_code == 201
    data = r.json()
    assert data["localidad_id"] == "777"
    assert data["localidad_match_tipo"] == "exacto"


@pytest.mark.asyncio
async def test_crear_localidad_duplicada_por_tilde_devuelve_409(client: AsyncClient, geo_san_jose):
    r1 = await client.post(BASE, json={"localidad": "San José", "departamento": "Tulumba"})
    assert r1.status_code == 201
    r2 = await client.post(BASE, json={"localidad": "San Jose", "departamento": "Tulumba"})
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "LOCALIDAD_DUPLICADA"


@pytest.mark.asyncio
async def test_actualizar_localidad_recalcula_localidad_id(client: AsyncClient, localidad_id: str, geo_san_jose):
    r = await client.patch(f"{BASE}/{localidad_id}", json={"localidad": "San José", "departamento": "Tulumba"})
    assert r.status_code == 200
    assert r.json()["localidad_id"] == "777"


# ── Convenio firmado (spec-ch-convenio-firmado.md) ─────────────────────────────

ID_FIRMADO = 9
ID_NOTIFICADO = 4


@pytest_asyncio.fixture
async def localidad_convenio(db_session: AsyncSession) -> str:
    db_session.add(EstadoCordobaHogar(
        id=ID_FIRMADO, label="Convenio Firmado", bg="#fff", text_color="#000", orden=10, dimension="juridico",
    ))
    db_session.add(EstadoCordobaHogar(
        id=ID_NOTIFICADO, label="Notificado", bg="#fff", text_color="#000", orden=3, dimension="juridico",
    ))
    await db_session.flush()
    lid = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid, orden=50, localidad="Pueblo Convenio", departamento="Test", ejuridico=ID_NOTIFICADO,
    ))
    await db_session.flush()
    return lid


@pytest.mark.asyncio
async def test_convenio_arranca_sin_firmar(client: AsyncClient, localidad_convenio: str):
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={"obs": "x"})
    assert r.status_code == 200
    assert r.json()["convenio_firmado"] is False
    assert r.json()["fecha_firma_convenio"] is None


@pytest.mark.asyncio
async def test_convenio_marcar_con_fecha_y_desmarcar_borra_la_fecha(client: AsyncClient, localidad_convenio: str):
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={
        "convenio_firmado": True, "fecha_firma_convenio": "2026-09-10",
    })
    assert r.status_code == 200
    assert r.json()["convenio_firmado"] is True
    assert r.json()["fecha_firma_convenio"] == "2026-09-10"

    r = await client.patch(f"{BASE}/{localidad_convenio}", json={"convenio_firmado": False})
    assert r.status_code == 200
    assert r.json()["convenio_firmado"] is False
    assert r.json()["fecha_firma_convenio"] is None


@pytest.mark.asyncio
async def test_convenio_firmado_sin_fecha_es_valido(client: AsyncClient, localidad_convenio: str):
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={"convenio_firmado": True})
    assert r.status_code == 200
    assert r.json()["convenio_firmado"] is True
    assert r.json()["fecha_firma_convenio"] is None


@pytest.mark.asyncio
async def test_convenio_fecha_sin_firma_da_422(client: AsyncClient, localidad_convenio: str):
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={"fecha_firma_convenio": "2026-09-10"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "FECHA_FIRMA_SIN_CONVENIO"


@pytest.mark.asyncio
async def test_convenio_fecha_futura_da_422(client: AsyncClient, localidad_convenio: str):
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={
        "convenio_firmado": True, "fecha_firma_convenio": "2999-01-01",
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "FECHA_FIRMA_FUTURA"


@pytest.mark.asyncio
async def test_convenio_pasar_al_estado_lo_marca_con_fecha_cambio(client: AsyncClient, localidad_convenio: str):
    # El formulario manda la casilla desmarcada: el cambio de estado manda igual (A1).
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={
        "ejuridico": ID_FIRMADO, "convenio_firmado": False, "fecha_firma_convenio": None,
        "fecha_cambio": "2026-08-01",
    })
    assert r.status_code == 200
    assert r.json()["convenio_firmado"] is True
    assert r.json()["fecha_firma_convenio"] == "2026-08-01"


@pytest.mark.asyncio
async def test_convenio_pasar_al_estado_respeta_la_fecha_cargada(client: AsyncClient, localidad_convenio: str):
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={
        "ejuridico": ID_FIRMADO, "convenio_firmado": True, "fecha_firma_convenio": "2026-07-15",
        "fecha_cambio": "2026-08-01",
    })
    assert r.json()["fecha_firma_convenio"] == "2026-07-15"


@pytest.mark.asyncio
async def test_convenio_avanzar_de_estado_no_lo_desmarca(client: AsyncClient, localidad_convenio: str):
    await client.patch(f"{BASE}/{localidad_convenio}", json={"ejuridico": ID_FIRMADO, "fecha_cambio": "2026-08-01"})
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={"ejuridico": ID_NOTIFICADO})
    assert r.status_code == 200
    assert r.json()["convenio_firmado"] is True
    assert r.json()["fecha_firma_convenio"] == "2026-08-01"


@pytest.mark.asyncio
async def test_convenio_desmarcar_con_el_estado_sin_cambiar_queda_desmarcado(client: AsyncClient, localidad_convenio: str):
    await client.patch(f"{BASE}/{localidad_convenio}", json={"ejuridico": ID_FIRMADO})
    r = await client.patch(f"{BASE}/{localidad_convenio}", json={
        "ejuridico": ID_FIRMADO, "convenio_firmado": False, "fecha_firma_convenio": None,
    })
    assert r.json()["convenio_firmado"] is False
    assert r.json()["fecha_firma_convenio"] is None


@pytest.mark.asyncio
async def test_convenio_crear_en_el_estado_lo_marca(client: AsyncClient, localidad_convenio: str):
    r = await client.post(BASE, json={"localidad": "Pueblo Nuevo", "departamento": "Test", "ejuridico": ID_FIRMADO})
    assert r.status_code in (200, 201)
    assert r.json()["convenio_firmado"] is True
    assert r.json()["fecha_firma_convenio"] == date.today().isoformat()
