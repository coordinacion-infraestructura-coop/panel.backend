"""POST /internal/privada/gestiones/sync — vinculación Vivienda -> Privada (ADR-020).

Sin auth (IAM-only) — se ejercita con el `client` fixture (que sí inyecta un usuario,
pero el endpoint no lo exige; lo relevante acá es el algoritmo de matching).
"""
from datetime import date

import pytest
import pytest_asyncio

from app.gestiones.models import Gestion
from app.territorial.models import GeoLocalidad

_HOY = date(2026, 1, 15)


@pytest_asyncio.fixture
async def geo(db_session):
    db_session.add(
        GeoLocalidad(id_geo="508", departamento="CALAMUCHITA", localidad="AMBOY", lat=-32.17, lon=-64.57, activo=True)
    )
    await db_session.flush()


def _payload(**overrides):
    base = {
        "caso_tipo": "cc",
        "caso_id": "caso-1",
        "id_legacy": "vivienda:cc:caso-1",
        "nro_expediente": None,
        "localidad": "AMBOY",
        "departamento": "CALAMUCHITA",
        "categoria_id": 1756700000003,
        "programa_id": 1756700001003,
        "area_id": 1756700002001,
        "ministerio_agencia_id": "MIN_GOBIERNO",
        "ok_gobernador": "SI",
        "ok_ministro": "SI",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_crea_gestion_nueva_sin_match(client, geo, db_session):
    r = await client.post("/internal/privada/gestiones/sync", json=_payload(nro_expediente="EXP-001"))
    assert r.status_code == 200
    body = r.json()
    assert body["resultado"] == "LINKED_NEW"
    assert body["gestion_id"]

    g = await db_session.get(Gestion, body["gestion_id"])
    assert g.id_legacy == "vivienda:cc:caso-1"
    assert g.origen == "SVC_VIVIENDA"
    assert g.categoria_id == 1756700000003
    assert g.programa_id == 1756700001003
    assert g.area_id == 1756700002001
    assert g.ministerio_agencia_id == "MIN_GOBIERNO"
    assert g.ok_gobernador == "SI" and g.ok_ministro == "SI"
    assert g.nro_expediente == "EXP-001"


@pytest.mark.asyncio
async def test_vincula_por_expediente_existente_y_sincroniza(client, geo, db_session):
    db_session.add(Gestion(
        id="g-1", estado="INGRESADO", urgencia="Media", detalle="obra vieja",
        departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508",
        nro_expediente="EXP-777", fecha_ingreso=_HOY,
        categoria_id=None, ok_gobernador="PENDIENTE", ok_ministro="PENDIENTE",
    ))
    await db_session.flush()

    r = await client.post("/internal/privada/gestiones/sync", json=_payload(nro_expediente="EXP-777"))
    assert r.status_code == 200
    body = r.json()
    assert body["resultado"] == "LINKED_EXISTING"
    assert body["gestion_id"] == "g-1"
    assert body["diff"]["categoria_id"] == {"antes": None, "despues": 1756700000003}
    assert body["diff"]["ok_gobernador"] == {"antes": "PENDIENTE", "despues": "SI"}

    await db_session.refresh(await db_session.get(Gestion, "g-1"))
    g = await db_session.get(Gestion, "g-1")
    assert g.id_legacy == "vivienda:cc:caso-1"
    assert g.categoria_id == 1756700000003
    assert g.detalle == "obra vieja"  # nunca se toca (fuera de whitelist)


@pytest.mark.asyncio
async def test_localidad_departamento_un_candidato_vincula(client, geo, db_session):
    db_session.add(Gestion(
        id="g-2", estado="INGRESADO", urgencia="Media", detalle="obra x",
        departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508", fecha_ingreso=_HOY,
    ))
    await db_session.flush()

    r = await client.post("/internal/privada/gestiones/sync", json=_payload())  # sin expediente
    assert r.status_code == 200
    assert r.json()["resultado"] == "LINKED_EXISTING"
    assert r.json()["gestion_id"] == "g-2"


@pytest.mark.asyncio
async def test_localidad_departamento_ambiguo_no_toca_nada(client, geo, db_session):
    db_session.add_all([
        Gestion(id="g-3", estado="INGRESADO", urgencia="Media", detalle="obra a",
                departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508", fecha_ingreso=_HOY),
        Gestion(id="g-4", estado="DERIVADO A SUAC", urgencia="Media", detalle="obra b",
                departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508", fecha_ingreso=_HOY),
    ])
    await db_session.flush()

    r = await client.post("/internal/privada/gestiones/sync", json=_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["resultado"] == "PENDING_REVIEW"
    assert body["motivo"] == "LOCALIDAD_DEPARTAMENTO_AMBIGUO"
    assert set(body["candidatos"]) == {"g-3", "g-4"}

    g3 = await db_session.get(Gestion, "g-3")
    g4 = await db_session.get(Gestion, "g-4")
    assert g3.categoria_id is None and g3.id_legacy is None
    assert g4.categoria_id is None and g4.id_legacy is None


@pytest.mark.asyncio
async def test_localidad_departamento_excluye_cerradas(client, geo, db_session):
    db_session.add_all([
        Gestion(id="g-5", estado="INGRESADO", urgencia="Media", detalle="obra activa",
                departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508", fecha_ingreso=_HOY),
        Gestion(id="g-6", estado="FINALIZADA", urgencia="Media", detalle="obra vieja",
                departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508", fecha_ingreso=_HOY),
    ])
    await db_session.flush()

    r = await client.post("/internal/privada/gestiones/sync", json=_payload())
    assert r.status_code == 200
    assert r.json()["resultado"] == "LINKED_EXISTING"
    assert r.json()["gestion_id"] == "g-5"


@pytest.mark.asyncio
async def test_localidad_departamento_excluye_ya_vinculadas_a_otro_caso(client, geo, db_session):
    db_session.add(Gestion(
        id="g-7", id_legacy="vivienda:ch:otro-caso", estado="INGRESADO", urgencia="Media",
        detalle="obra de otro caso", departamento="CALAMUCHITA", localidad="AMBOY",
        geo_id="508", fecha_ingreso=_HOY,
    ))
    await db_session.flush()

    r = await client.post("/internal/privada/gestiones/sync", json=_payload())
    assert r.status_code == 200
    # no le roba el vínculo a g-7: sin más candidatos, crea una gestión nueva
    assert r.json()["resultado"] == "LINKED_NEW"
    assert r.json()["gestion_id"] != "g-7"


@pytest.mark.asyncio
async def test_expediente_ya_vinculado_a_otro_caso(client, geo, db_session):
    db_session.add(Gestion(
        id="g-8", id_legacy="vivienda:ch:otro-caso", estado="INGRESADO", urgencia="Media",
        detalle="obra de otro caso", departamento="CALAMUCHITA", localidad="AMBOY",
        geo_id="508", fecha_ingreso=_HOY, nro_expediente="EXP-999",
    ))
    await db_session.flush()

    r = await client.post("/internal/privada/gestiones/sync", json=_payload(nro_expediente="EXP-999"))
    assert r.status_code == 200
    body = r.json()
    assert body["resultado"] == "PENDING_REVIEW"
    assert body["motivo"] == "EXPEDIENTE_YA_VINCULADO_OTRO_CASO"


@pytest.mark.asyncio
async def test_geo_invalida_en_creacion(client, db_session):
    r = await client.post("/internal/privada/gestiones/sync", json=_payload(
        localidad="NO EXISTE", departamento="NO EXISTE", nro_expediente="EXP-XX",
    ))
    assert r.status_code == 200
    body = r.json()
    assert body["resultado"] == "ERROR"
    assert body["motivo"] == "GEO_INVALIDO"

    total = (await db_session.execute(
        __import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(Gestion)
    ))
    assert total.scalar_one() == 0


@pytest.mark.asyncio
async def test_reintento_idempotente_no_duplica(client, geo, db_session):
    p = _payload(nro_expediente="EXP-IDEM")
    r1 = await client.post("/internal/privada/gestiones/sync", json=p)
    assert r1.json()["resultado"] == "LINKED_NEW"
    gid = r1.json()["gestion_id"]

    r2 = await client.post("/internal/privada/gestiones/sync", json=p)
    assert r2.json()["resultado"] == "LINKED_EXISTING"
    assert r2.json()["gestion_id"] == gid

    from sqlalchemy import func, select
    total = (await db_session.execute(select(func.count()).select_from(Gestion))).scalar_one()
    assert total == 1


@pytest.mark.asyncio
async def test_no_pisa_expediente_si_no_viene(client, geo, db_session):
    db_session.add(Gestion(
        id="g-9", estado="INGRESADO", urgencia="Media", detalle="obra x",
        departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508", fecha_ingreso=_HOY,
        nro_expediente="EXP-PROPIO",
    ))
    await db_session.flush()

    r = await client.post("/internal/privada/gestiones/sync", json=_payload(nro_expediente=None))
    assert r.status_code == 200
    assert r.json()["resultado"] == "LINKED_EXISTING"

    g = await db_session.get(Gestion, "g-9")
    assert g.nro_expediente == "EXP-PROPIO"
