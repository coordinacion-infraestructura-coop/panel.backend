"""Tests de integración para el módulo asignaciones."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.programas.service import seed_programas

BASE_BENE = "/api/v1/vivienda/beneficiarios"
BASE_EXP = "/api/v1/vivienda/expedientes"
BASE_ASIG = "/api/v1/vivienda/asignaciones"

_ASIG_BASE = {
    "tipo_bien": "VIVIENDA",
    "identificador_bien": "CASA-001",
    "domicilio_bien": "Calle Falsa 123, Córdoba",
}


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def programa_id(db_session: AsyncSession) -> str:
    await seed_programas(db_session)
    await db_session.commit()
    from app.programas.repository import get_by_codigo
    p = await get_by_codigo(db_session, "CORDOBA_HOGAR")
    return p.id


@pytest_asyncio.fixture
async def beneficiario_id(client: AsyncClient) -> str:
    r = await client.post(BASE_BENE, json={"dni": "77777777", "nombre": "Luis", "apellido": "Gomez"})
    return r.json()["id"]


@pytest_asyncio.fixture
async def expediente_asignado(client: AsyncClient, beneficiario_id: str, programa_id: str) -> str:
    """Crea un expediente y lo lleva al estado ASIGNADO."""
    r = await client.post(BASE_EXP, json={
        "beneficiario_id": beneficiario_id,
        "programa_id": programa_id,
    })
    eid = r.json()["id"]
    for estado in ["EN_EVALUACION", "APROBADO", "EN_LISTA_ESPERA", "ASIGNADO"]:
        await client.post(f"{BASE_EXP}/{eid}/transicion", json={"estado_nuevo": estado})
    return eid


# ── Crear asignación ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_asignacion_ok(client: AsyncClient, expediente_asignado: str):
    r = await client.post(BASE_ASIG, json={
        **_ASIG_BASE,
        "expediente_id": expediente_asignado,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["expediente_id"] == expediente_asignado
    assert data["tipo_bien"] == "VIVIENDA"
    assert data["identificador_bien"] == "CASA-001"


@pytest.mark.asyncio
async def test_crear_asignacion_expediente_inexistente(client: AsyncClient):
    r = await client.post(BASE_ASIG, json={
        **_ASIG_BASE,
        "expediente_id": "00000000-0000-0000-0000-000000000000",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_crear_asignacion_expediente_no_asignado(
    client: AsyncClient, beneficiario_id: str, programa_id: str
):
    """Debe fallar si el expediente no está en estado ASIGNADO."""
    r = await client.post(BASE_EXP, json={
        "beneficiario_id": beneficiario_id,
        "programa_id": programa_id,
    })
    eid = r.json()["id"]
    # Expediente en INGRESADO — no puede ser asignado

    r2 = await client.post(BASE_ASIG, json={**_ASIG_BASE, "expediente_id": eid})
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "CONFLICTO_ESTADO"


@pytest.mark.asyncio
async def test_crear_asignacion_duplicada_devuelve_409(
    client: AsyncClient, expediente_asignado: str
):
    await client.post(BASE_ASIG, json={**_ASIG_BASE, "expediente_id": expediente_asignado})
    r = await client.post(BASE_ASIG, json={
        **_ASIG_BASE,
        "expediente_id": expediente_asignado,
        "identificador_bien": "CASA-002",
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_tipo_bien_invalido_devuelve_422(client: AsyncClient, expediente_asignado: str):
    r = await client.post(BASE_ASIG, json={
        **_ASIG_BASE,
        "expediente_id": expediente_asignado,
        "tipo_bien": "DEPARTAMENTO",  # no está en TipoBien enum
    })
    assert r.status_code == 422


# ── Listar asignaciones ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_asignaciones_vacio(client: AsyncClient):
    r = await client.get(BASE_ASIG)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_listar_asignaciones(client: AsyncClient, expediente_asignado: str):
    await client.post(BASE_ASIG, json={**_ASIG_BASE, "expediente_id": expediente_asignado})
    r = await client.get(BASE_ASIG)
    assert len(r.json()) == 1


# ── Actualizar asignación ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_asignacion(client: AsyncClient, expediente_asignado: str):
    cr = await client.post(BASE_ASIG, json={**_ASIG_BASE, "expediente_id": expediente_asignado})
    asig_id = cr.json()["id"]

    r = await client.patch(f"{BASE_ASIG}/{asig_id}", json={"observaciones": "Escritura pendiente"})
    assert r.status_code == 200
    assert r.json()["observaciones"] == "Escritura pendiente"


# ── Control de acceso ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_asignacion_requiere_supervisor(
    client_operador: AsyncClient, db_session: AsyncSession, programa_id: str
):
    """Rol Operador no puede crear asignaciones (requiere Admin|Supervisor).
    El expediente se crea directamente en DB para evitar conflicto de fixtures entre
    client (Admin) y client_operador, ya que ambos sobreescriben dependency_overrides.
    """
    from app.beneficiarios.models import Beneficiario
    from app.expedientes.models import Expediente, EstadoExpediente

    bene = Beneficiario(dni="66655544", nombre="Test", apellido="User", created_by="test@test.com",
                        updated_by="test@test.com")
    db_session.add(bene)
    await db_session.flush()

    exp = Expediente(
        numero_expediente="VIV-2026-999002",
        beneficiario_id=bene.id,
        programa_id=programa_id,
        estado=EstadoExpediente.ASIGNADO.value,
        created_by="test@test.com",
        updated_by="test@test.com",
    )
    db_session.add(exp)
    await db_session.flush()

    r = await client_operador.post(BASE_ASIG, json={
        **_ASIG_BASE,
        "expediente_id": exp.id,
    })
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_lectura_asignaciones_permitida_a_consulta(client_consulta: AsyncClient):
    r = await client_consulta.get(BASE_ASIG)
    assert r.status_code == 200
