"""Tests de endpoints de gestiones/catálogos/informe sobre datos sembrados (SQLite)."""
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio

from app.catalogos.models import CatCategoriaGeneral, CatEstado
from app.gestiones.models import Gestion, GestionEvento
from app.territorial.models import GeoLocalidad, LocalidadInfo
from tests.conftest import CONSULTA_USER, INVITADO_USER

NOW = datetime(2026, 8, 31, 13, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def seed(db_session):
    db = db_session
    db.add_all([
        GeoLocalidad(id_geo="508", departamento="CALAMUCHITA", localidad="AMBOY", lat=-32.17, lon=-64.57, activo=True),
        CatEstado(id="INGRESADO", nombre="INGRESADO", orden=10, activo=True),
        CatEstado(id="FINALIZADA", nombre="FINALIZADA", orden=40, activo=True),
        CatCategoriaGeneral(id="CAT_OBRA_DE_GAS", nombre="Obra de gas", orden=10, activo=True),
        CatCategoriaGeneral(id="CAT_OTROS", nombre="Otros", orden=99, activo=True),
        LocalidadInfo(departamento="CALAMUCHITA", localidad="AMBOY", habitantes=1000, electores=800,
                      intendente_jefe_comunal="X", partido_politico="Y", color_semaforo="verde"),
    ])
    g1 = Gestion(
        id="11111111-1111-1111-1111-111111111111", id_legacy="leg-1",
        origen="APP", estado="INGRESADO", fecha_ingreso=date(2026, 8, 31), fecha_estado=NOW,
        urgencia="Media", ministerio_agencia_id="MIN_GOBIERNO", categoria_general_id="CAT_OBRA_DE_GAS",
        detalle="OBRA DE GAS", departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508",
        lat=-32.17, lon=-64.57, costo_moneda="ARS", created_at=NOW, updated_at=NOW,
        created_by="op@test.com", updated_by="op@test.com",
    )
    g2 = Gestion(
        id="22222222-2222-2222-2222-222222222222",
        origen="APP", estado="FINALIZADA", fecha_ingreso=date(2026, 7, 1), fecha_estado=NOW,
        urgencia="Alta", ministerio_agencia_id="MIN_COOPERATIVAS_MUTUALES", categoria_general_id="CAT_OTROS",
        detalle="construccion de viviendas sociales", departamento="CALAMUCHITA", localidad="AMBOY",
        geo_id="508", lat=-32.17, lon=-64.57, created_at=NOW, updated_at=NOW,
    )
    db.add_all([g1, g2])
    db.add(GestionEvento(
        id="ev-1", gestion_id=g1.id, fecha_evento=NOW, usuario="op@test.com", rol_usuario="Supervisor",
        tipo_evento="CREACION", estado_nuevo="INGRESADO",
        metadata_json={"departamento": "CALAMUCHITA", "localidad": "AMBOY"},
    ))
    await db.flush()
    return {"g1": g1.id, "g2": g2.id}


@pytest.mark.asyncio
async def test_list_gestiones(client, seed):
    r = await client.get("/api/v1/privada/gestiones", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {"items", "total", "limit", "offset"} == set(body)
    item = body["items"][0]
    assert set(item) == {
        "id_gestion", "departamento", "localidad", "estado", "urgencia",
        "ministerio_agencia_id", "categoria_general_id", "tipo_gestion", "canal_origen",
        "detalle", "costo_estimado", "costo_moneda", "nro_expediente", "fecha_ingreso",
        "dias_transcurridos",
    }


@pytest.mark.asyncio
async def test_list_filtros(client, seed):
    r = await client.get("/api/v1/privada/gestiones", params={"estado": "FINALIZADA"})
    assert r.json()["total"] == 1
    r = await client.get("/api/v1/privada/gestiones", params={"q": "viviendas"})
    assert r.json()["total"] == 1
    r = await client.get("/api/v1/privada/gestiones", params={"departamento": "calamuchita"})
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_get_por_uuid_y_legacy(client, seed):
    r = await client.get(f"/api/v1/privada/gestiones/{seed['g1']}")
    assert r.status_code == 200
    d = r.json()
    assert d["origen"] == "APP" and d["is_deleted"] is False
    assert len(set(d)) == 32
    r2 = await client.get("/api/v1/privada/gestiones/leg-1")
    assert r2.status_code == 200 and r2.json()["id_gestion"] == seed["g1"]
    assert (await client.get("/api/v1/privada/gestiones/nope")).status_code == 404


@pytest.mark.asyncio
async def test_eventos_metadata_es_objeto(client, seed):
    r = await client.get(f"/api/v1/privada/gestiones/{seed['g1']}/eventos")
    assert r.status_code == 200
    evs = r.json()
    assert isinstance(evs[0]["metadata_json"], dict)


@pytest.mark.asyncio
async def test_crear_y_cambiar_estado_setea_fecha_finalizacion(client, seed):
    r = await client.post("/api/v1/privada/gestiones", json={
        "ministerio_agencia_id": "MIN_GOBIERNO", "categoria_general_id": "CAT_OTROS",
        "detalle": "algo nuevo", "departamento": "CALAMUCHITA", "localidad": "AMBOY",
    })
    assert r.status_code == 201
    gid = r.json()["id_gestion"]

    r = await client.post(f"/api/v1/privada/gestiones/{gid}/cambiar-estado", json={"nuevo_estado": "FINALIZADA"})
    assert r.status_code == 200
    d = (await client.get(f"/api/v1/privada/gestiones/{gid}")).json()
    assert d["estado"] == "FINALIZADA"
    assert d["fecha_finalizacion"] == date.today().isoformat()  # RE-9


@pytest.mark.asyncio
async def test_cambiar_estado_lock_optimista(client, seed):
    r = await client.post(
        f"/api/v1/privada/gestiones/{seed['g1']}/cambiar-estado",
        json={"nuevo_estado": "DERIVADO A SUAC", "updated_at": "2000-01-01T00:00:00+00:00"},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_delete_es_soft(client, seed):
    r = await client.delete(f"/api/v1/privada/gestiones/{seed['g1']}")
    assert r.status_code == 200
    assert (await client.get(f"/api/v1/privada/gestiones/{seed['g1']}")).status_code == 404
    assert (await client.get("/api/v1/privada/gestiones")).json()["total"] == 1


@pytest.mark.asyncio
async def test_resumen_territorial_shape(client, seed):
    r = await client.get("/api/v1/privada/gestiones/resumen-territorial", params={"departamento": "CALAMUCHITA", "localidad": "AMBOY"})
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"scope", "territorio_info", "localidad_info", "departamento_info", "metricas", "gestiones"}
    assert d["scope"] == "localidad"
    assert d["departamento_info"] is None
    assert set(d["metricas"]) == {"total_gestiones", "abiertas", "finalizadas", "urgentes"}
    assert d["metricas"] == {"total_gestiones": 2, "abiertas": 1, "finalizadas": 1, "urgentes": 1}
    ev = d["gestiones"][0]["eventos"]
    if ev:
        assert isinstance(ev[0]["metadata_json"], str)  # en resumen-territorial va como string


@pytest.mark.asyncio
async def test_rollup_territorial(client, seed):
    r = await client.get("/api/v1/privada/gestiones/rollup-territorial")
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["departamento"] == "CALAMUCHITA"
    assert rows[0]["total_gestiones"] == 2
    assert rows[0]["finalizadas"] == 1


@pytest.mark.asyncio
async def test_departamentos_info_read_only(client, seed):
    r = await client.get("/api/v1/privada/departamentos-info", params={"departamento": "CALAMUCHITA"})
    assert r.status_code == 200
    assert r.json()["departamento"] == "CALAMUCHITA"


@pytest.mark.asyncio
async def test_catalogos(client, seed):
    r = await client.get("/api/v1/privada/catalogos/estados")
    assert [e["id"] for e in r.json()] == ["INGRESADO", "FINALIZADA"]
    r = await client.get("/api/v1/privada/catalogos/departamentos")
    assert r.json() == ["CALAMUCHITA"]
    r = await client.get("/api/v1/privada/catalogos/localidades", params={"departamento": "CALAMUCHITA"})
    assert r.json() == ["AMBOY"]
    r = await client.get("/api/v1/privada/catalogos/geo", params={"departamento": "CALAMUCHITA", "localidad": "AMBOY"})
    assert r.json()["id_geo"] == "508"
    r = await client.get("/api/v1/privada/catalogos/geo", params={"departamento": "X", "localidad": "Y"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_me(client):
    r = await client.get("/api/v1/privada/me")
    assert r.status_code == 200
    assert set(r.json()) == {"email", "nombre", "rol", "modulos"}
    assert r.json()["modulos"] == []


@pytest.mark.asyncio
async def test_informe_resumen(client, seed):
    r = await client.get("/api/v1/privada/informe/cooperativas/resumen",
                         params={"fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31"})
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"total", "fecha_desde", "fecha_hasta", "por_tema"}
    temas = {t["tema"]: t for t in d["por_tema"]}
    assert "Gas" in temas and "Vivienda" in temas
    assert set(temas["Gas"]) == {"tema", "total", "finalizadas", "en_curso", "archivadas", "urgentes"}
    assert temas["Vivienda"]["urgentes"] == 1  # g2 es Alta


@pytest.mark.asyncio
async def test_resumen_territorial_scope_departamento(client, seed):
    r = await client.get("/api/v1/privada/gestiones/resumen-territorial", params={"departamento": "CALAMUCHITA"})
    d = r.json()
    assert d["scope"] == "departamento"
    assert d["localidad_info"] is None
    assert set(d["departamento_info"]) == {
        "departamento", "habitantes", "electores", "legislador_departamental", "partido_politico",
        "legislador_sabana1", "partido_politico_sabana1", "legislador_sabana2",
        "partido_politico_sabana2", "updated_at", "updated_by",
    }


@pytest.mark.asyncio
async def test_crear_geo_invalida_400(client, seed):
    r = await client.post("/api/v1/privada/gestiones", json={
        "ministerio_agencia_id": "M", "categoria_general_id": "CAT_OTROS", "detalle": "x",
        "departamento": "NADA", "localidad": "NADA",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_gestion_genera_evento(client, seed):
    r = await client.patch(f"/api/v1/privada/gestiones/{seed['g1']}", json={"observaciones": "nueva obs"})
    assert r.status_code == 200 and r.json()["observaciones"] == "nueva obs"
    evs = (await client.get(f"/api/v1/privada/gestiones/{seed['g1']}/eventos")).json()
    assert any(e["tipo_evento"] == "ACTUALIZA_DATO" and e["campo_modificado"] == "observaciones" for e in evs)


@pytest.mark.asyncio
async def test_cambiar_estado_registra_actualiza_dato(client, seed):
    r = await client.post(f"/api/v1/privada/gestiones/{seed['g1']}/cambiar-estado",
                          json={"nuevo_estado": "DERIVADO A SUAC", "nro_expediente": "EXP-9", "comentario": "ok"})
    assert r.status_code == 200
    evs = (await client.get(f"/api/v1/privada/gestiones/{seed['g1']}/eventos")).json()
    tipos = [e["tipo_evento"] for e in evs]
    assert "CAMBIO_ESTADO" in tipos
    assert any(e["tipo_evento"] == "ACTUALIZA_DATO" and e["campo_modificado"] == "nro_expediente" for e in evs)


@pytest.mark.asyncio
async def test_patch_cambia_geo_valida(client, seed, db_session):
    # agrego otra localidad geo válida
    db_session.add(GeoLocalidad(id_geo="999", departamento="CALAMUCHITA", localidad="EMBALSE",
                                lat=-32.2, lon=-64.4, activo=True))
    await db_session.flush()
    r = await client.patch(f"/api/v1/privada/gestiones/{seed['g1']}", json={"localidad": "EMBALSE"})
    assert r.status_code == 200 and r.json()["localidad"] == "EMBALSE" and r.json()["geo_id"] == "999"
    r2 = await client.patch(f"/api/v1/privada/gestiones/{seed['g1']}", json={"localidad": "NADA"})
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_put_localidad_info_crea_fila_nueva(client, seed, db_session):
    db_session.add(GeoLocalidad(id_geo="777", departamento="CALAMUCHITA", localidad="LOS MOLINOS",
                                lat=-32.0, lon=-64.5, activo=True))
    await db_session.flush()
    r = await client.put("/api/v1/privada/localidades-info", json={
        "departamento": "CALAMUCHITA", "localidad": "LOS MOLINOS", "habitantes": 300, "electores": 250,
        "intendente_jefe_comunal": "Nuevo Jefe", "partido_politico": "PJ",
    })
    assert r.status_code == 200 and r.json()["habitantes"] == 300 and r.json()["intendente_jefe_comunal"] == "Nuevo Jefe"


@pytest.mark.asyncio
async def test_cambiar_estado_por_id_legacy(client, seed):
    r = await client.post("/api/v1/privada/gestiones/leg-1/cambiar-estado", json={"nuevo_estado": "ARCHIVADO", "comentario": "x"})
    assert r.status_code == 200
    assert (await client.get(f"/api/v1/privada/gestiones/{seed['g1']}")).json()["estado"] == "ARCHIVADO"


@pytest.mark.asyncio
async def test_put_localidad_info(client, seed):
    r = await client.put("/api/v1/privada/localidades-info", json={
        "departamento": "CALAMUCHITA", "localidad": "AMBOY", "habitantes": 5000, "electores": 4000,
        "intendente_jefe_comunal": "Nuevo", "partido_politico": "P",
        "tipo_localidad": "IGNORADO", "color_semaforo": "IGNORADO",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["habitantes"] == 5000 and d["intendente_jefe_comunal"] == "Nuevo"
    # tipo_localidad / color_semaforo NO se tocan por el PUT (paridad con el viejo)
    assert d["color_semaforo"] == "verde"


@pytest.mark.asyncio
async def test_informe_temporal_y_puntos_y_por_depto(client, seed):
    p = {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31"}
    t = (await client.get("/api/v1/privada/informe/cooperativas/temporal", params=p)).json()
    assert all(set(x) == {"mes", "tema", "total"} for x in t)
    pd = (await client.get("/api/v1/privada/informe/cooperativas/por-departamento", params=p)).json()
    assert all(set(x) == {"tema", "departamento", "total", "finalizadas"} for x in pd)
    pu = (await client.get("/api/v1/privada/informe/cooperativas/puntos", params=p)).json()
    assert all("lat" in x and "detalle_corto" in x for x in pu)
    # g1 (Gas) y g2 (Vivienda) tienen lat/lon -> 2 puntos
    assert len(pu) == 2


@pytest.mark.asyncio
async def test_permisos(client, seed, as_user):
    as_user(INVITADO_USER)
    assert (await client.get("/api/v1/privada/gestiones")).status_code == 403
    as_user(CONSULTA_USER)
    assert (await client.get("/api/v1/privada/gestiones")).status_code == 200
    assert (await client.post("/api/v1/privada/gestiones", json={
        "ministerio_agencia_id": "M", "categoria_general_id": "C", "detalle": "d",
        "departamento": "CALAMUCHITA", "localidad": "AMBOY",
    })).status_code == 403
