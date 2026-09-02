"""CRUD de los 3 catálogos editables (E1 / ADR-010) + guard 409 en DELETE."""
from datetime import date

import pytest

from app.catalogos_editables.models import Categoria
from app.gestiones.models import Gestion
from tests.conftest import CONSULTA_USER, OPERADOR_USER


@pytest.mark.asyncio
async def test_crud_categorias(client, db_session):
    # crear
    r = await client.post("/api/v1/privada/categorias", json={"label": "Test Cat", "orden": 5, "bg": "#fff", "text_color": "#000"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert isinstance(cid, int) and r.json()["label"] == "Test Cat"

    # listar (sólo activos por default)
    r = await client.get("/api/v1/privada/categorias")
    assert any(c["id"] == cid for c in r.json())

    # patch → desactivar
    r = await client.patch(f"/api/v1/privada/categorias/{cid}", json={"label": "Renombrada", "activo": False})
    assert r.status_code == 200 and r.json()["label"] == "Renombrada"
    activos = (await client.get("/api/v1/privada/categorias")).json()
    todos = (await client.get("/api/v1/privada/categorias", params={"incluir_inactivos": "true"})).json()
    assert not any(c["id"] == cid for c in activos)
    assert any(c["id"] == cid for c in todos)

    # delete (no está en uso)
    assert (await client.delete(f"/api/v1/privada/categorias/{cid}")).status_code == 200
    assert (await client.delete(f"/api/v1/privada/categorias/{cid}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_guard_409(client, db_session):
    db_session.add(Categoria(id=999001, label="En Uso", orden=1))
    db_session.add(Gestion(
        id="g-cat-1", estado="INGRESADO", urgencia="Media", detalle="x",
        departamento="D", localidad="L", geo_id="1", fecha_ingreso=date(2026, 1, 1),
        categoria_id=999001,
    ))
    await db_session.flush()
    r = await client.delete("/api/v1/privada/categorias/999001")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CATEGORIA_EN_USO"


@pytest.mark.asyncio
async def test_programa_codigo_duplicado_409(client, db_session):
    assert (await client.post("/api/v1/privada/programas", json={"label": "P1", "codigo": "DUP"})).status_code == 201
    r = await client.post("/api/v1/privada/programas", json={"label": "P2", "codigo": "DUP"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CODIGO_DUPLICADO"


@pytest.mark.asyncio
async def test_admin_roles(client, db_session, as_user):
    as_user(OPERADOR_USER)
    assert (await client.post("/api/v1/privada/categorias", json={"label": "x"})).status_code == 403
    as_user(CONSULTA_USER)
    assert (await client.get("/api/v1/privada/categorias")).status_code == 200
    assert (await client.delete("/api/v1/privada/categorias/1")).status_code == 403


@pytest.mark.asyncio
async def test_gestion_con_campos_e1(client, db_session):
    db_session.add(Categoria(id=888001, label="Vivienda", orden=1))
    from app.territorial.models import GeoLocalidad
    db_session.add(GeoLocalidad(id_geo="1", departamento="COLON", localidad="JESUS MARIA", lat=-30, lon=-64, activo=True))
    await db_session.flush()

    r = await client.post("/api/v1/privada/gestiones", json={
        "ministerio_agencia_id": "M", "categoria_general_id": "C", "detalle": "obra",
        "departamento": "COLON", "localidad": "JESUS MARIA",
        "categoria_id": 888001, "ok_gobernador": "SI", "ok_ministro": "PENDIENTE",
        "acciones_implementadas": "se hizo x",
    })
    assert r.status_code == 201
    gid = r.json()["id_gestion"]
    d = (await client.get(f"/api/v1/privada/gestiones/{gid}")).json()
    assert d["categoria_id"] == 888001
    assert d["ok_gobernador"] == "SI" and d["ok_ministro"] == "PENDIENTE"
    assert d["acciones_implementadas"] == "se hizo x"

    # filtro por ok_gobernador
    r = await client.get("/api/v1/privada/gestiones", params={"ok_gobernador": "SI"})
    assert r.json()["total"] == 1
    assert (await client.get("/api/v1/privada/gestiones", params={"ok_gobernador": "NO"})).json()["total"] == 0
    # valor inválido → 422
    assert (await client.get("/api/v1/privada/gestiones", params={"ok_gobernador": "quizas"})).status_code == 422
