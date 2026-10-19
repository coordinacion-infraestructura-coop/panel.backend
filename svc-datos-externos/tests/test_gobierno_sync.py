"""Sync del nomenclador de Gobierno + ficha de localidad
(spec-datos-externos-fase1-nomenclador-demografia.md §9). La planilla y el
resolver de localidades van siempre mockeados."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import rollup
from app.config import settings
from app.geo_censo.models import ExtGeoCenso
from app.gobierno import sync as gob_sync
from app.gobierno.models import ExtGobEnte, ExtGobLocalidad, ExtGobSyncLog

HEAD_NOM = ["ID_LOC", "LOCALIDADES", "ID_DPTO", "DEPARTAMENTOS", "ID_COPA", "TIPO"]
HEAD_VISTA = [
    "ID_LOC", "LOCALIDAD", "ID_DPTO", "DEPARTAMENTO", "PARTIDO", "POBLACION", "ATP", "FOCOM PURO", "COPA",
    "FOFINDES", "ATP/COPA+FOFIN", "ADELANTO COPA", "OBRAS", "FONDO FEDERAL", "FONDO AMBIENTAL", "GUARDIAS",
    "TOTAL", "TOTAL x HABIT",
]

# Valor centinela para verificar que nada restringido se filtra a `anomalias`.
SECRETO_PARTIDO = "PARTIDO-CENTINELA"


def nomenclador(n_locales: int = 400, extra: list[list] | None = None) -> list[list]:
    filas = [["NOMENCLADOR INDEC"], HEAD_NOM]
    for i in range(n_locales):
        filas.append([140001 + i, f"LOCALIDAD {i}", 14007, "CALAMUCHITA", 500 + i, "MU" if i % 2 else "CO"])
    filas.append([428, "COMUNIDAD REGIONAL - CALAMUCHITA", 1, "CALAMUCHITA"])
    filas.append(["1ZR", "ZONA RURAL - CALAMUCHITA", 1, "CALAMUCHITA"])
    return filas + (extra or [])


def fila_vista(codigo, **kw) -> list:
    base = {
        "LOCALIDAD": "X", "ID_DPTO": 14007, "DEPARTAMENTO": "CALAMUCHITA", "PARTIDO": SECRETO_PARTIDO,
        "POBLACION": 1000, "ATP": 44, "FOCOM PURO": 25, "COPA": 389.99, "FOFINDES": 103.4,
        "ATP/COPA+FOFIN": 0.09, "ADELANTO COPA": 2.5, "OBRAS": 0, "FONDO FEDERAL": 30, "FONDO AMBIENTAL": 0,
        "GUARDIAS": "", "TOTAL": 594.9, "TOTAL x HABIT": 1685424.4,
    }
    base.update(kw)
    return [codigo] + [base[h] for h in HEAD_VISTA[1:]]


def vista(filas: list[list] | None = None, head: list[str] | None = None) -> list[list]:
    return [head or HEAD_VISTA] + (filas if filas is not None else [fila_vista(140001), fila_vista("1ZR")])


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_gob_nomenclador_id", "NOM")
    monkeypatch.setattr(settings, "google_sheet_gob_resumen_vista_id", "RES")
    monkeypatch.setattr(settings, "gob_localidades_sync_enabled", True)


def mock_sheets(nom, loc):
    async def fake(spreadsheet_id, rango, render="FORMATTED_VALUE"):
        assert render == "UNFORMATTED_VALUE"
        valor = nom if spreadsheet_id == "NOM" else loc
        if isinstance(valor, Exception):
            raise valor
        return valor

    return patch("app.gobierno.sync.google_sheets.get_values", new=fake)


def mock_resolver(fn=None):
    async def fake(items, cantidades=None):
        return [fn(dep, loc) if fn else (None, None) for dep, loc in items]

    return patch("app.gobierno.sync.geo_resolver.resolver_localidades", new=fake)


async def correr(db, nom=None, loc=None, resolver=None):
    with mock_sheets(nom if nom is not None else nomenclador(), loc if loc is not None else vista()):
        with mock_resolver(resolver):
            return await gob_sync.sync_localidades(db, disparado_por="test")


# ── Normalización y clasificación ─────────────────────────────────────────────

@pytest.mark.parametrize("raw,esperado", [
    (142007, "142007"), (142007.0, "142007"), ("142.007", "142007"), ("142,007", "142007"),
    (" 142007 ", "142007"), ("1ZR", "1ZR"), ("1zr", "1ZR"), ("25ZR", "25ZR"), (428, "428"),
    ("#N/A", None), ("", None), (None, None), (True, None), (0, None), ("TOTAL", None),
])
def test_normalizar_codigo(raw, esperado):
    assert gob_sync.normalizar_codigo(raw) == esperado


@pytest.mark.parametrize("codigo,tipo,esperado", [
    ("142007", "MU", "local"), ("142007", "CO", "local"), ("428", None, "comunidad_regional"),
    ("1ZR", None, "zona_rural"), ("142007", None, None), ("14200", "MU", None), (None, "MU", None),
    ("142007", "XX", None),
])
def test_clasificar_fila(codigo, tipo, esperado):
    assert gob_sync.clasificar_fila(codigo, tipo) == esperado


# ── Corrida completa ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_corrida_ok_carga_locales_entes_y_ficha(db_session: AsyncSession):
    res = await correr(db_session, resolver=lambda dep, loc: ("77", "exacto") if loc == "LOCALIDAD 0" else (None, None))

    assert res.estado == "ok"
    assert res.gobiernos_locales == 400 and res.entes == 2
    assert res.con_id_geo == 1 and res.sin_id_geo == 399

    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert (loc.nombre_gob, loc.departamento_gob, loc.codigo_dpto_indec, loc.id_copa, loc.tipo) == (
        "LOCALIDAD 0", "CALAMUCHITA", "14007", 500, "CO")
    assert (loc.id_geo, loc.match_tipo) == ("77", "exacto")
    assert loc.poblacion_2022_gob == 1000 and loc.partido == SECRETO_PARTIDO
    # Sin fuente desde que la ficha sale de la Vista (spec §3.2).
    for campo in ("superficie_km2", "poblacion_2010", "electores", "empleados", "masa_salarial", "intendente",
                  "reelecto", "continuidad", "legislador", "partido_legislador", "contacto_intendente"):
        assert getattr(loc, campo) is None, campo

    zr = await db_session.get(ExtGobEnte, "1ZR")
    assert (zr.tipo_ente, zr.departamento, zr.poblacion_2022, zr.poblacion_2010) == ("zona_rural", "CALAMUCHITA", 1000, None)
    cr = await db_session.get(ExtGobEnte, "428")
    assert cr.tipo_ente == "comunidad_regional" and cr.poblacion_2022 is None

    logs = (await db_session.execute(select(ExtGobSyncLog))).scalars().all()
    assert {l.fuente: l.estado for l in logs} == {"nomenclador": "ok", "resumen_vista": "ok"}


@pytest.mark.asyncio
async def test_codigos_con_separador_de_miles_y_filas_invalidas(db_session: AsyncSession):
    extra = [["149.999", "CON PUNTO", 14007, "CALAMUCHITA", 9999, "MU"], ["#N/A", "ROTA", "", "", "", "MU"], []]
    res = await correr(db_session, nom=nomenclador(extra=extra))
    assert res.gobiernos_locales == 401
    assert await db_session.get(ExtGobLocalidad, "149999") is not None
    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "nomenclador"))).scalar_one()
    assert [a for a in log.anomalias if a["tipo"] == "fila_invalida"] == [{"tipo": "fila_invalida", "fila": 406}]


# ── Lista blanca ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_columnas_reordenadas_o_extra_no_cambian_lo_guardado(db_session: AsyncSession):
    head = list(reversed(HEAD_VISTA)) + ["COLUMNA NUEVA"]
    fila = list(reversed(fila_vista(140001))) + ["dato que no debe entrar"]
    await correr(db_session, loc=[head, fila])
    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert loc.partido == SECRETO_PARTIDO and loc.poblacion_2022_gob == 1000
    assert not hasattr(loc, "columna_nueva")
    # Las columnas de montos de la Vista no entran (spec §3.2).
    assert not any(hasattr(loc, c) for c in ("atp", "copa", "fofindes", "total"))


@pytest.mark.asyncio
async def test_columna_esperada_faltante_en_la_vista_deja_la_corrida_parcial(db_session: AsyncSession):
    head = [h for h in HEAD_VISTA if h != "PARTIDO"]
    res = await correr(db_session, loc=[head, [140001] + [1] * (len(head) - 1)])
    assert res.estado == "parcial"
    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert loc is not None and loc.poblacion_2022_gob is None  # nomenclador conservado, ficha sin tocar
    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "resumen_vista"))).scalar_one()
    assert log.estado == "fallido" and "PARTIDO" in log.anomalias[0]["detalle"]


@pytest.mark.asyncio
async def test_falla_de_lectura_de_la_vista_conserva_el_nomenclador(db_session: AsyncSession):
    res = await correr(db_session, loc=RuntimeError("403"))
    assert res.estado == "parcial" and res.gobiernos_locales == 400


@pytest.mark.asyncio
async def test_encabezado_faltante_en_nomenclador_falla_sin_tocar_datos(db_session: AsyncSession):
    nom = nomenclador()
    nom[1] = ["ID_LOC", "LOCALIDADES", "ID_DPTO", "DEPARTAMENTOS", "TIPO"]
    with pytest.raises(gob_sync.SyncFallido):
        await correr(db_session, nom=nom)
    assert (await db_session.execute(select(ExtGobLocalidad))).scalars().all() == []
    log = (await db_session.execute(select(ExtGobSyncLog))).scalar_one()
    assert log.estado == "fallido"


# ── Freno de seguridad ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_freno_de_seguridad_no_da_de_baja_el_padron(db_session: AsyncSession):
    await correr(db_session)
    await db_session.commit()
    with pytest.raises(gob_sync.SyncFallido):
        await correr(db_session, nom=nomenclador(n_locales=10))
    vivos = (await db_session.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars().all()
    assert len(vivos) == 400


# ── SAVEPOINT, baja lógica, reactivación ──────────────────────────────────────

@pytest.mark.asyncio
async def test_una_fila_mala_no_frena_el_lote(db_session: AsyncSession):
    # ID_COPA repetido viola el UNIQUE: esa fila falla, el resto entra.
    extra = [[149998, "COPA REPETIDA", 14007, "CALAMUCHITA", 500, "MU"]]
    res = await correr(db_session, nom=nomenclador(extra=extra))
    assert res.estado == "parcial"
    assert await db_session.get(ExtGobLocalidad, "149998") is None
    assert await db_session.get(ExtGobLocalidad, "140400") is not None
    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "nomenclador"))).scalar_one()
    assert log.filas_error == 1 and log.filas_upsert == 402


@pytest.mark.asyncio
async def test_baja_logica_y_reactivacion(db_session: AsyncSession):
    extra = [[149997, "TEMPORAL", 14007, "CALAMUCHITA", 9997, "MU"]]
    await correr(db_session, nom=nomenclador(extra=extra))
    await correr(db_session)
    loc = await db_session.get(ExtGobLocalidad, "149997")
    assert loc.deleted_at is not None
    await correr(db_session, nom=nomenclador(extra=extra))
    await db_session.refresh(loc)
    assert loc.deleted_at is None


@pytest.mark.asyncio
async def test_resolver_caido_no_pisa_un_id_geo_ya_resuelto(db_session: AsyncSession):
    await correr(db_session, resolver=lambda dep, loc: ("77", "exacto") if loc == "LOCALIDAD 0" else (None, None))
    await correr(db_session)  # resolver devuelve todo None
    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert loc.id_geo == "77"


# ── Conversión de valores y privacidad ────────────────────────────────────────

@pytest.mark.asyncio
async def test_valores_invalidos_van_a_null_y_anomalias_no_filtran_restringidos(db_session: AsyncSession):
    filas = [
        fila_vista(140001, POBLACION=-5),
        fila_vista(140002, POBLACION="s/d"),
        fila_vista(999999),
    ]
    await correr(db_session, loc=vista(filas))
    a, b = [await db_session.get(ExtGobLocalidad, k) for k in ("140001", "140002")]
    assert a.poblacion_2022_gob is None and b.poblacion_2022_gob is None
    assert a.partido == SECRETO_PARTIDO

    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "resumen_vista"))).scalar_one()
    invalidos = [(a["codigo"], a["campo"]) for a in log.anomalias if a["tipo"] == "valor_invalido"]
    assert invalidos == [("140001", "poblacion_2022_gob"), ("140002", "poblacion_2022_gob")]
    assert {"tipo": "codigo_fuera_del_nomenclador", "codigo": "999999"} in log.anomalias
    volcado = json.dumps([l.anomalias for l in (await db_session.execute(select(ExtGobSyncLog))).scalars().all()])
    for secreto in (SECRETO_PARTIDO, "s/d", "-5"):
        assert secreto not in volcado


# ── Cierre del Censo ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cierre_del_censo_completa_nulos_y_no_pisa_resueltos(db_session: AsyncSession):
    db_session.add_all([
        ExtGeoCenso(id="a", id_geo=None, codigo_indec="140001", categoria="CO", localidad_censo="L0", poblacion_2022=1000),
        ExtGeoCenso(id="b", id_geo="5", codigo_indec="140002", categoria="MU", localidad_censo="L1", poblacion_2022=555, match_tipo="exacto"),
        ExtGeoCenso(id="c", id_geo=None, codigo_indec="140003", categoria="CO", localidad_censo="L2"),
        ExtGeoCenso(id="d", id_geo=None, codigo_indec="999999", categoria="CO", localidad_censo="FUERA"),
    ])
    await db_session.flush()
    ids = {"LOCALIDAD 0": "77", "LOCALIDAD 1": "88", "LOCALIDAD 2": "5"}  # el "5" ya lo usa otra fila del censo
    res = await correr(
        db_session,
        loc=vista([fila_vista(140001), fila_vista(140002)]),
        resolver=lambda dep, loc: (ids[loc], "exacto") if loc in ids else (None, None),
    )
    assert res.censo_cerrados == 1
    a, b, c = [await db_session.get(ExtGeoCenso, k) for k in ("a", "b", "c")]
    assert (a.id_geo, a.match_tipo, a.departamento_censo) == ("77", "nomenclador_gob", "CALAMUCHITA")
    assert (b.id_geo, b.match_tipo) == ("5", "exacto")
    assert c.id_geo is None

    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "nomenclador"))).scalar_one()
    assert {"tipo": "censo_id_geo_en_conflicto", "codigo": "140003"} in log.anomalias
    assert {"tipo": "censo_sin_nomenclador", "codigo": "999999"} in log.anomalias
    assert {"tipo": "poblacion_difiere_del_censo", "codigo": "140002"} in log.anomalias
    assert {"tipo": "poblacion_difiere_del_censo", "codigo": "140001"} not in log.anomalias
    assert {"tipo": "nomenclador_sin_censo", "codigo": "140004"} in log.anomalias


# ── Rollup y endpoints ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollup_suma_publicos_y_ficha_gobierno(db_session: AsyncSession):
    await correr(db_session, resolver=lambda dep, loc: ("77", "exacto") if loc == "LOCALIDAD 0" else (None, None))
    filas = await rollup.rollup_territorial(db_session)
    assert len(filas) == 1
    r = filas[0]
    assert (r["id_geo"], r["codigo_indec"], r["categoria"]) == ("77", "140001", "CO")
    assert r["superficie_km2"] is None and r["poblacion_2010"] is None  # sin fuente desde la Vista
    assert r["poblacion_2022"] is None  # la población expuesta es la del Censo, no la de Gobierno
    assert "poblacion_2022_gob" not in r
    assert r["ficha_gobierno"] == {
        "electores": None, "empleados": None, "masa_salarial": None, "intendente": None,
        "reelecto": None, "partido": SECRETO_PARTIDO, "continuidad": None, "legislador": None,
        "partido_legislador": None, "contacto_intendente": None,
    }


@pytest.mark.asyncio
async def test_rollup_sin_partido_no_manda_ficha(db_session: AsyncSession):
    await correr(
        db_session,
        loc=vista([fila_vista(140001, PARTIDO="")]),
        resolver=lambda dep, loc: ("77", "exacto") if loc == "LOCALIDAD 0" else (None, None),
    )
    (r,) = await rollup.rollup_territorial(db_session)
    assert r["ficha_gobierno"] is None


@pytest.mark.asyncio
async def test_endpoints_sync_estado_y_zonas_rurales(client: AsyncClient):
    with mock_sheets(nomenclador(), vista()), mock_resolver():
        resp = await client.post("/internal/datos-externos/gobierno/localidades/sync", params={"triggered_by": "test"})
    assert resp.status_code == 200
    assert resp.json()["gobiernos_locales"] == 400

    estado = (await client.get("/internal/datos-externos/gobierno/localidades/sync-estado")).json()
    assert [e["fuente"] for e in estado] == ["nomenclador", "resumen_vista"]

    zr = (await client.get("/internal/datos-externos/zonas-rurales")).json()
    assert zr == [{"departamento": "CALAMUCHITA", "poblacion_2022": 1000, "poblacion_2010": None}]


@pytest.mark.asyncio
async def test_endpoint_sync_502_si_falla_el_nomenclador_y_503_si_esta_apagado(client: AsyncClient, monkeypatch):
    with mock_sheets(RuntimeError("boom"), vista()), mock_resolver():
        resp = await client.post("/internal/datos-externos/gobierno/localidades/sync")
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "GOB_SYNC_FALLIDO"

    monkeypatch.setattr(settings, "gob_localidades_sync_enabled", False)
    resp = await client.post("/internal/datos-externos/gobierno/localidades/sync")
    assert resp.status_code == 503
