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
HEAD_LOC = [
    "ID_LOC", "LOCALIDAD", "TIPO", "SUPERFICIE", "POBLACION 2022", "ELECTORES", "CATEGORIA POBLACION",
    "EMPLEADOS", "EMPLEADOS/POBLACION", "EMPLEADOS POR KM2", "INTENDENTE", "REELECTO", "PARTIDO",
    "CONTINUIDAD", "FOTO", "LEGISLADOR", "PARTIDO_LEG", "POBLACION 2010", "CATEGORIA POBLACION 2010",
    "MASA SALARIAL", "celular",
]

# Valores centinela para verificar que nada restringido se filtra a `anomalias`.
SECRETO_NOMBRE = "INTENDENTE-CENTINELA"
SECRETO_CONTACTO = "3519999999"


def nomenclador(n_locales: int = 400, extra: list[list] | None = None) -> list[list]:
    filas = [["NOMENCLADOR INDEC"], HEAD_NOM]
    for i in range(n_locales):
        filas.append([140001 + i, f"LOCALIDAD {i}", 14007, "CALAMUCHITA", 500 + i, "MU" if i % 2 else "CO"])
    filas.append([428, "COMUNIDAD REGIONAL - CALAMUCHITA", 1, "CALAMUCHITA"])
    filas.append(["1ZR", "ZONA RURAL - CALAMUCHITA", 1, "CALAMUCHITA"])
    return filas + (extra or [])


def fila_loc(codigo, **kw) -> list:
    base = {
        "LOCALIDAD": "X", "TIPO": "M", "SUPERFICIE": 12.5, "POBLACION 2022": 1000, "ELECTORES": 800,
        "CATEGORIA POBLACION": "A", "EMPLEADOS": 20, "EMPLEADOS/POBLACION": 0.02, "EMPLEADOS POR KM2": 1.6,
        "INTENDENTE": SECRETO_NOMBRE, "REELECTO": "SI", "PARTIDO": "PARTIDO X", "CONTINUIDAD": "NO",
        "FOTO": "https://drive/x", "LEGISLADOR": "LEG", "PARTIDO_LEG": "PL", "POBLACION 2010": 900,
        "CATEGORIA POBLACION 2010": "A", "MASA SALARIAL": 1234567.8, "celular": int(SECRETO_CONTACTO),
    }
    base.update(kw)
    return [codigo] + [base[h] for h in HEAD_LOC[1:]]


def datos_loc(filas: list[list] | None = None, head: list[str] | None = None) -> list[list]:
    return [head or HEAD_LOC] + (filas if filas is not None else [fila_loc(140001), fila_loc("1ZR", **{"SUPERFICIE": 0})])


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_gob_nomenclador_id", "NOM")
    monkeypatch.setattr(settings, "google_sheet_gob_resumen_general_id", "RES")
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
    with mock_sheets(nom if nom is not None else nomenclador(), loc if loc is not None else datos_loc()):
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
    assert float(loc.superficie_km2) == 12.5 and loc.poblacion_2010 == 900 and loc.poblacion_2022_gob == 1000
    assert loc.electores == 800 and loc.empleados == 20 and float(loc.masa_salarial) == 1234567.8
    assert loc.intendente == SECRETO_NOMBRE and loc.reelecto is True and loc.continuidad is False
    assert loc.partido == "PARTIDO X" and loc.legislador == "LEG" and loc.partido_legislador == "PL"
    assert loc.contacto_intendente == SECRETO_CONTACTO

    zr = await db_session.get(ExtGobEnte, "1ZR")
    assert (zr.tipo_ente, zr.departamento, zr.poblacion_2022, zr.poblacion_2010) == ("zona_rural", "CALAMUCHITA", 1000, 900)
    cr = await db_session.get(ExtGobEnte, "428")
    assert cr.tipo_ente == "comunidad_regional" and cr.poblacion_2022 is None

    logs = (await db_session.execute(select(ExtGobSyncLog))).scalars().all()
    assert {l.fuente: l.estado for l in logs} == {"nomenclador": "ok", "datos_loc": "ok"}


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
    head = list(reversed(HEAD_LOC)) + ["COLUMNA NUEVA"]
    fila = list(reversed(fila_loc(140001))) + ["dato que no debe entrar"]
    await correr(db_session, loc=[head, fila])
    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert loc.intendente == SECRETO_NOMBRE and loc.poblacion_2010 == 900 and float(loc.superficie_km2) == 12.5
    assert not hasattr(loc, "columna_nueva") and not hasattr(loc, "foto")


@pytest.mark.asyncio
async def test_columna_esperada_faltante_en_datos_loc_deja_la_corrida_parcial(db_session: AsyncSession):
    head = [h for h in HEAD_LOC if h != "ELECTORES"]
    res = await correr(db_session, loc=[head, [140001] + [1] * (len(head) - 1)])
    assert res.estado == "parcial"
    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert loc is not None and loc.intendente is None and loc.superficie_km2 is None  # nomenclador conservado, ficha sin tocar
    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "datos_loc"))).scalar_one()
    assert log.estado == "fallido" and "ELECTORES" in log.anomalias[0]["detalle"]


@pytest.mark.asyncio
async def test_falla_de_lectura_de_datos_loc_conserva_el_nomenclador(db_session: AsyncSession):
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
    fila = fila_loc(
        140001, **{"ELECTORES": -5, "MASA SALARIAL": "s/d", "REELECTO": "TAL VEZ", "CONTINUIDAD": "sí",
                   "celular": SECRETO_CONTACTO * 5, "SUPERFICIE": "12,5"}
    )
    await correr(db_session, loc=datos_loc([fila, fila_loc(999999)]))
    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert loc.electores is None and loc.masa_salarial is None and loc.reelecto is None
    assert loc.continuidad is True and loc.contacto_intendente is None and float(loc.superficie_km2) == 12.5

    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "datos_loc"))).scalar_one()
    campos = {a["campo"] for a in log.anomalias if a["tipo"] == "valor_invalido"}
    assert campos == {"electores", "masa_salarial", "reelecto", "contacto_intendente"}
    assert {"tipo": "codigo_fuera_del_nomenclador", "codigo": "999999"} in log.anomalias
    volcado = json.dumps([l.anomalias for l in (await db_session.execute(select(ExtGobSyncLog))).scalars().all()])
    for secreto in (SECRETO_NOMBRE, SECRETO_CONTACTO, "TAL VEZ", "s/d", "-5"):
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
        loc=datos_loc([fila_loc(140001), fila_loc(140002)]),
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
    assert r["superficie_km2"] == 12.5 and r["poblacion_2010"] == 900
    assert r["poblacion_2022"] is None  # la población expuesta es la del Censo, no la de Gobierno
    assert "poblacion_2022_gob" not in r
    assert r["ficha_gobierno"] == {
        "electores": 800, "empleados": 20, "masa_salarial": 1234567.8, "intendente": SECRETO_NOMBRE,
        "reelecto": True, "partido": "PARTIDO X", "continuidad": False, "legislador": "LEG",
        "partido_legislador": "PL", "contacto_intendente": SECRETO_CONTACTO,
    }


@pytest.mark.asyncio
async def test_endpoints_sync_estado_y_zonas_rurales(client: AsyncClient):
    with mock_sheets(nomenclador(), datos_loc()), mock_resolver():
        resp = await client.post("/internal/datos-externos/gobierno/localidades/sync", params={"triggered_by": "test"})
    assert resp.status_code == 200
    assert resp.json()["gobiernos_locales"] == 400

    estado = (await client.get("/internal/datos-externos/gobierno/localidades/sync-estado")).json()
    assert [e["fuente"] for e in estado] == ["nomenclador", "datos_loc"]

    zr = (await client.get("/internal/datos-externos/zonas-rurales")).json()
    assert zr == [{"departamento": "CALAMUCHITA", "poblacion_2022": 1000, "poblacion_2010": 900}]


@pytest.mark.asyncio
async def test_endpoint_sync_502_si_falla_el_nomenclador_y_503_si_esta_apagado(client: AsyncClient, monkeypatch):
    with mock_sheets(RuntimeError("boom"), datos_loc()), mock_resolver():
        resp = await client.post("/internal/datos-externos/gobierno/localidades/sync")
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "GOB_SYNC_FALLIDO"

    monkeypatch.setattr(settings, "gob_localidades_sync_enabled", False)
    resp = await client.post("/internal/datos-externos/gobierno/localidades/sync")
    assert resp.status_code == 503
