"""Áreas de acceso por secretaría (spec-portal-areas-de-acceso.md)."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.checklist_tecnico.models import CatalogoEstadoExpediente, CatalogoItemEstado
from app.cordon_cuneta.models import MunicipioCordonCuneta
from tests.conftest import _make_client_fixture

CC = "/api/v1/vivienda/cordon-cuneta"
CH = "/api/v1/vivienda/cordoba-hogar"
CHECKLIST = "/api/v1/vivienda/checklist-tecnico"
PORTAL = "/api/v1/portal"
USUARIOS = f"{PORTAL}/admin/usuarios"

# El caso que motivó el spec: edita el Checklist y solo mira Cordón Cuneta.
client_tecnico_ve_cc = _make_client_fixture(AuthUser(
    uid="t1", email="tecnico.cc@test.com", role="Operador", secretarias=["vivienda"],
    areas={"vivienda": {"checklist": "edicion", "cc": "lectura"}},
))
# El nivel del área no le da más que su rol.
client_consulta_con_edicion = _make_client_fixture(AuthUser(
    uid="t2", email="consulta.cc@test.com", role="Consulta", secretarias=["vivienda"],
    areas={"vivienda": {"cc": "edicion"}},
))
# Tiene la secretaría, pero ninguna área marcada (B6).
client_vivienda_sin_areas = _make_client_fixture(AuthUser(
    uid="t3", email="sin.areas@test.com", role="Operador", secretarias=["vivienda"],
))


@pytest_asyncio.fixture
async def municipio(db_session: AsyncSession) -> str:
    mid = str(uuid.uuid4())
    db_session.add_all([
        MunicipioCordonCuneta(id=mid, orden=1, municipio="Pueblo", departamento="Depto"),
        CatalogoEstadoExpediente(id=1, label="A ESPERA de DOC.TÉCNICA", orden=0, en_ruta=True),
        CatalogoItemEstado(id=1, label="A ESPERA de DOC.TÉCNICA", orden=0),
    ])
    await db_session.flush()
    return mid


# ── Control de acceso ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_area_en_lectura_ve_pero_no_edita(client_tecnico_ve_cc: AsyncClient, municipio: str):
    assert (await client_tecnico_ve_cc.get(CC)).status_code == 200
    r = await client_tecnico_ve_cc.patch(f"{CC}/{municipio}", json={"obs": "x"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AREA_SIN_ACCESO"


@pytest.mark.asyncio
async def test_sin_el_area_no_ve_el_panel(client_tecnico_ve_cc: AsyncClient):
    r = await client_tecnico_ve_cc.get(CH)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AREA_SIN_ACCESO"


@pytest.mark.asyncio
async def test_area_en_edicion_edita_el_checklist(client_tecnico_ve_cc: AsyncClient, municipio: str):
    r = await client_tecnico_ve_cc.patch(f"{CHECKLIST}/cc/{municipio}", json={"estado_expediente_id": 1})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_nivel_edicion_no_supera_al_rol(client_consulta_con_edicion: AsyncClient, municipio: str):
    assert (await client_consulta_con_edicion.get(CC)).status_code == 200
    r = await client_consulta_con_edicion.patch(f"{CC}/{municipio}", json={"obs": "x"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "PERMISO_INSUFICIENTE"


@pytest.mark.asyncio
async def test_secretaria_sin_areas_no_ve_nada(client_vivienda_sin_areas: AsyncClient):
    for url in (CC, CH, f"{CHECKLIST}/catalogos", "/api/v1/vivienda/programas-tablero"):
        assert (await client_vivienda_sin_areas.get(url)).status_code == 403, url


@pytest.mark.asyncio
async def test_otra_secretaria_no_ve_vivienda(client_privada: AsyncClient):
    """Cierra el hueco de §1: antes alcanzaba con el rol."""
    assert (await client_privada.get(CC)).status_code == 403


@pytest.mark.asyncio
async def test_infraestructura_sigue_leyendo_los_paneles(client_infraestructura: AsyncClient):
    """Infraestructura y Supervisión cargan comunicaciones en los paneles: siguen leyéndolos."""
    assert (await client_infraestructura.get(CC)).status_code == 200


@pytest.mark.asyncio
async def test_cualquier_area_ve_los_tableros(client_tecnico_dgv: AsyncClient):
    assert (await client_tecnico_dgv.get("/api/v1/vivienda/programas-tablero")).status_code == 200
    assert (await client_tecnico_dgv.get(CC)).status_code == 403


# ── Portal ────────────────────────────────────────────────────────────────────

_USUARIO = {"email": "nuevo@test.com", "rol": "Operador", "secretarias": ["vivienda"]}


@pytest.mark.asyncio
async def test_catalogo_de_areas(client: AsyncClient):
    r = await client.get(f"{PORTAL}/areas")
    assert r.status_code == 200
    assert {a["area"] for a in r.json()["vivienda"]} == {"cc", "ch", "ml", "checklist"}


@pytest.mark.asyncio
async def test_alta_con_areas(client: AsyncClient):
    areas = [
        {"secretaria": "vivienda", "area": "checklist", "nivel": "edicion"},
        {"secretaria": "vivienda", "area": "cc", "nivel": "lectura"},
    ]
    r = await client.post(USUARIOS, json={**_USUARIO, "areas": areas})
    assert r.status_code == 201, r.text
    assert sorted(r.json()["areas"], key=lambda a: a["area"]) == sorted(areas, key=lambda a: a["area"])


@pytest.mark.asyncio
@pytest.mark.parametrize("area", [
    {"secretaria": "privada", "area": "cc", "nivel": "lectura"},       # secretaría no asignada
    {"secretaria": "vivienda", "area": "obras", "nivel": "lectura"},   # área inexistente
])
async def test_area_invalida_422(client: AsyncClient, area: dict):
    r = await client.post(USUARIOS, json={**_USUARIO, "areas": [area]})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "AREA_INVALIDA"


@pytest.mark.asyncio
async def test_nivel_invalido_422(client: AsyncClient):
    r = await client.post(USUARIOS, json={**_USUARIO, "areas": [{"secretaria": "vivienda", "area": "cc", "nivel": "total"}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_quitar_la_secretaria_borra_sus_areas(client: AsyncClient):
    await client.post(USUARIOS, json={**_USUARIO, "areas": [{"secretaria": "vivienda", "area": "cc", "nivel": "edicion"}]})
    r = await client.put(f"{USUARIOS}/nuevo@test.com", json={"secretarias": ["privada"]})
    assert r.status_code == 200
    assert r.json()["areas"] == []


@pytest.mark.asyncio
async def test_editar_areas_valida_contra_las_secretarias_actuales(client: AsyncClient):
    await client.post(USUARIOS, json=_USUARIO)
    ok = await client.put(f"{USUARIOS}/nuevo@test.com", json={"areas": [{"secretaria": "vivienda", "area": "ml", "nivel": "lectura"}]})
    assert ok.status_code == 200
    assert ok.json()["areas"] == [{"secretaria": "vivienda", "area": "ml", "nivel": "lectura"}]
    mal = await client.put(f"{USUARIOS}/nuevo@test.com", json={"areas": [{"secretaria": "gralgob", "area": "ml", "nivel": "lectura"}]})
    assert mal.status_code == 422


@pytest.mark.asyncio
async def test_me_devuelve_areas(client: AsyncClient):
    await client.post(USUARIOS, json={
        "email": "admin@test.com", "rol": "Admin", "secretarias": ["vivienda"],
        "areas": [{"secretaria": "vivienda", "area": "cc", "nivel": "edicion"}],
    })
    r = await client.get(f"{PORTAL}/me")
    assert r.json()["areas"] == [{"secretaria": "vivienda", "area": "cc", "nivel": "edicion"}]


@pytest.mark.asyncio
async def test_tecnico_dgv_ya_no_es_un_rol(client: AsyncClient):
    r = await client.post(USUARIOS, json={**_USUARIO, "rol": "TecnicoDGV"})
    assert r.status_code == 422
