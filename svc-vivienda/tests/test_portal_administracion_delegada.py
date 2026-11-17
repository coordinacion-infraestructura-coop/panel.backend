"""Administración delegada por secretaría (spec-portal-administracion-delegada.md, ADR-035)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.checklist_tecnico.models import CatalogoEstadoExpediente
from app.portal import repository
from tests.conftest import _make_client_fixture

USUARIOS = "/api/v1/portal/admin/usuarios"
CATALOGO = "/api/v1/vivienda/checklist-tecnico/admin/estado-expediente"
DELEGADO = "delegado@test.com"

client_delegado = _make_client_fixture(AuthUser(
    uid="d1", email=DELEGADO, role="Supervisor", secretarias=["vivienda"],
    areas={"vivienda": {"usuarios": "edicion", "checklist": "edicion"}},
))
client_supervisor_comun = _make_client_fixture(AuthUser(
    uid="d2", email="sup@test.com", role="Supervisor", secretarias=["vivienda"],
    areas={"vivienda": {"checklist": "lectura", "cc": "edicion"}},
))
client_operador_con_usuarios = _make_client_fixture(AuthUser(
    uid="d3", email="op@test.com", role="Operador", secretarias=["vivienda"],
    areas={"vivienda": {"usuarios": "edicion", "checklist": "edicion"}},
))
client_solo_usuarios = _make_client_fixture(AuthUser(
    uid="d4", email="solo.usuarios@test.com", role="Supervisor", secretarias=["vivienda"],
    areas={"vivienda": {"usuarios": "edicion"}},
))

_AREA_CC = {"secretaria": "vivienda", "area": "cc", "nivel": "edicion"}


def _nuevo(**extra) -> dict:
    return {"email": "nuevo@test.com", "rol": "Operador", "secretarias": ["vivienda"], "areas": [_AREA_CC], **extra}


@pytest_asyncio.fixture
async def usuarios(db_session: AsyncSession) -> None:
    alta = repository.create_usuario
    await alta(db_session, DELEGADO, None, "Supervisor", ["vivienda"], "seed",
               areas=[{"secretaria": "vivienda", "area": "usuarios", "nivel": "edicion"}])
    await alta(db_session, "solo.viv@test.com", None, "Operador", ["vivienda"], "seed", areas=[_AREA_CC])
    await alta(db_session, "mixto@test.com", None, "Operador", ["vivienda", "privada"], "seed")
    await alta(db_session, "privada@test.com", None, "Operador", ["privada"], "seed")
    await alta(db_session, "admin.viv@test.com", None, "Admin", ["vivienda"], "seed")
    await alta(db_session, "otro.delegado@test.com", None, "Supervisor", ["vivienda"], "seed",
               areas=[{"secretaria": "vivienda", "area": "usuarios", "nivel": "edicion"}])


# ── Quién administra ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_supervisor_sin_area_usuarios_no_administra(client_supervisor_comun: AsyncClient):
    r = await client_supervisor_comun.get(USUARIOS)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_operador_con_area_usuarios_no_administra(client_operador_con_usuarios: AsyncClient):
    assert (await client_operador_con_usuarios.get(USUARIOS)).status_code == 403


# ── Alcance de lectura ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lista_solo_usuarios_exclusivos_de_vivienda(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.get(USUARIOS)
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()}
    assert "solo.viv@test.com" in emails
    assert emails.isdisjoint({"mixto@test.com", "privada@test.com", "admin.viv@test.com"})


@pytest.mark.asyncio
async def test_usuario_fuera_de_alcance_da_404(client_delegado: AsyncClient, usuarios):
    for email in ("mixto@test.com", "privada@test.com", "admin.viv@test.com"):
        assert (await client_delegado.get(f"{USUARIOS}/{email}")).status_code == 404
        assert (await client_delegado.put(f"{USUARIOS}/{email}", json={"activo": False})).status_code == 404


# ── Alta ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alta_de_supervisor_de_vivienda(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.post(USUARIOS, json=_nuevo(rol="Supervisor"))
    assert r.status_code == 201, r.text
    assert r.json()["secretarias"] == ["vivienda"]


@pytest.mark.asyncio
async def test_alta_con_otra_secretaria(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.post(USUARIOS, json=_nuevo(secretarias=["vivienda", "privada"], areas=[]))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "SECRETARIA_FUERA_DE_ALCANCE"


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["Admin", "Autoridad"])
async def test_alta_con_rol_fuera_de_alcance(client_delegado: AsyncClient, usuarios, rol: str):
    r = await client_delegado.post(USUARIOS, json=_nuevo(rol=rol))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ROL_FUERA_DE_ALCANCE"


@pytest.mark.asyncio
async def test_no_puede_otorgar_area_usuarios(client_delegado: AsyncClient, usuarios):
    area = {"secretaria": "vivienda", "area": "usuarios", "nivel": "edicion"}
    r = await client_delegado.post(USUARIOS, json=_nuevo(rol="Supervisor", areas=[area]))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "AREA_FUERA_DE_ALCANCE"
    r = await client_delegado.put(f"{USUARIOS}/solo.viv@test.com", json={"areas": [{**area, "nivel": "lectura"}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_email_existente_en_otra_secretaria_409_generico(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.post(USUARIOS, json=_nuevo(email="privada@test.com"))
    assert r.status_code == 409
    assert "privada" not in r.json()["detail"]["message"].lower()


# ── Edición ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edita_y_desactiva_usuario_de_vivienda(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.put(f"{USUARIOS}/solo.viv@test.com", json={"rol": "Consulta", "activo": False})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "Consulta"
    assert r.json()["activo"] is False


@pytest.mark.asyncio
async def test_no_se_edita_a_si_mismo(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.put(f"{USUARIOS}/{DELEGADO}", json={"rol": "Operador"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "AUTO_EDICION"


@pytest.mark.asyncio
async def test_no_edita_a_otro_delegado(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.put(f"{USUARIOS}/otro.delegado@test.com", json={"activo": False})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_no_escala_rol_al_editar(client_delegado: AsyncClient, usuarios):
    r = await client_delegado.put(f"{USUARIOS}/solo.viv@test.com", json={"rol": "Admin"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_no_borra(client_delegado: AsyncClient, usuarios):
    assert (await client_delegado.delete(f"{USUARIOS}/solo.viv@test.com")).status_code == 403


# ── El área "usuarios" no abre pantallas ─────────────────────────────────────

@pytest.mark.asyncio
async def test_area_usuarios_no_abre_tableros(client_solo_usuarios: AsyncClient):
    r = await client_solo_usuarios.get("/api/v1/vivienda/programas-tablero")
    assert r.status_code == 403


# ── Catálogos del Checklist ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def estado(db_session: AsyncSession) -> int:
    db_session.add(CatalogoEstadoExpediente(id=1, label="A ESPERA", orden=0, en_ruta=True))
    await db_session.flush()
    return 1


@pytest.mark.asyncio
async def test_supervisor_con_checklist_edicion_administra_catalogo(client_delegado: AsyncClient, estado: int):
    r = await client_delegado.post(CATALOGO, json={"label": "NUEVO ESTADO", "orden": 5})
    assert r.status_code == 201, r.text
    r = await client_delegado.patch(f"{CATALOGO}/{estado}", json={"label": "A ESPERA (editado)"})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_supervisor_con_checklist_lectura_no_administra_catalogo(client_supervisor_comun: AsyncClient):
    r = await client_supervisor_comun.post(CATALOGO, json={"label": "X", "orden": 5})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_operador_no_administra_catalogo(client_operador_con_usuarios: AsyncClient):
    r = await client_operador_con_usuarios.post(CATALOGO, json={"label": "X", "orden": 5})
    assert r.status_code == 403
