"""ATP Interno de Gobierno (spec-atp-interno.md): parseo, sync, tablero y endpoint interno."""
from datetime import date
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp_interno import sync as interno_sync
from app.atp_interno.models import AtpInternoPago, AtpInternoSyncLog
from app.config import settings
from tests.conftest import AUTORIDAD_SIN_SECRETARIA_USER, CONSULTA_USER, OPERADOR_USER

ENC = ["ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "FECHA", "MONTO", "REFERENTE"]
REF = "PERSONA DE PRUEBA"
# 46029 = 2026-01-07; 46300 = 2026-10-05; 6693568 = serial imposible, como en la planilla real.
FILAS = [
    ENC,
    [142007, "EMBALSE", "CALAMUCHITA", 46029, 10_000_000, REF],
    [142007, "EMBALSE", "CALAMUCHITA", 46300, 5_000_000, REF + "  "],
    ["140.105", "COSQUÍN", "PUNILLA", 46300, "20.000.000", "OTRA PERSONA"],
    [140105, "COSQUÍN", "PUNILLA", 6693568, 1_000_000, "OTRA PERSONA"],
    ["#N/A", "SIN CODIGO", "PUNILLA", 46300, 1_000_000, REF],
    [140105, "COSQUÍN", "PUNILLA", 46300, "", REF],
    ["", "", "", "", "", ""],
]
SYNC = "/internal/sync/atp-interno"
URL = "/api/v1/gralgob/tablero/atp-interno"


def _sheet(rows=None, error=None):
    mock = AsyncMock(side_effect=error) if error else AsyncMock(return_value=rows)
    return patch("app.integrations.google_sheets.get_values", new=mock)


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_atp_interno_id", "sheet-test")
    monkeypatch.setattr(settings, "atp_interno_anio_planilla", 2026)


# ── Parseo ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,esperado", [(142007, "142007"), ("142.007", "142007"), ("142,007", "142007"), (142007.0, "142007"), ("#N/A", None), (14200, None), (None, None), (True, None)])
def test_codigo_indec(raw, esperado):
    assert interno_sync.codigo_indec(raw) == esperado


@pytest.mark.parametrize("raw,esperado", [(46029, date(2026, 1, 7)), (6693568, None), ("7/1/2026", date(2026, 1, 7)), ("", None), ("ayer", None)])
def test_fecha(raw, esperado):
    assert interno_sync.fecha(raw) == esperado


def test_parsear_descarta_e_informa():
    p = interno_sync.parsear(FILAS, 2026)
    assert p.leidas == 6 and p.descartadas == 2 and len(p.filas) == 4
    assert sorted(a.tipo for a in p.anomalias) == ["fecha_invalida", "sin_codigo", "sin_monto"]
    rota = next(f for f in p.filas if f["fecha"] is None)
    assert rota["anio"] == 2026 and rota["codigo_indec"] == "140105"
    assert next(f for f in p.filas if f["fila"] == 3)["referente"] == REF  # espacios normalizados


def test_parsear_ubica_columnas_por_nombre():
    reordenadas = [["Monto", "Fecha", "Id_Loc"], [100, 46029, 142007]]
    f = interno_sync.parsear(reordenadas, 2026).filas[0]
    assert (f["codigo_indec"], f["monto"], f["fecha"], f["localidad"], f["referente"]) == ("142007", 100.0, date(2026, 1, 7), None, None)


def test_parsear_falla_sin_columnas_obligatorias():
    with pytest.raises(interno_sync.SheetReadError, match="MONTO"):
        interno_sync.parsear([["ID_LOC", "FECHA"], [142007, 46029]], 2026)


# ── Sync ──────────────────────────────────────────────────────────────────────


async def _cantidad(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(AtpInternoPago))).scalar_one()


async def test_sync_carga_y_reemplaza(client: AsyncClient, db_session: AsyncSession):
    with _sheet(FILAS):
        r = await client.post(SYNC)
    assert r.status_code == 200
    b = r.json()
    assert (b["estado"], b["filas_cargadas"], b["filas_descartadas"]) == ("ok", 4, 2)
    assert await _cantidad(db_session) == 4
    # Segunda corrida con una fila menos: reemplaza, no acumula.
    with _sheet(FILAS[:-3]):
        r = await client.post(SYNC)
    assert r.json()["filas_cargadas"] == 4
    assert await _cantidad(db_session) == 4


async def test_sync_reemplaza_solo_el_anio_de_la_planilla(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    with _sheet(FILAS):
        await client.post(SYNC)
    monkeypatch.setattr(settings, "atp_interno_anio_planilla", 2027)
    with _sheet([ENC, [142007, "EMBALSE", "CALAMUCHITA", 46400, 1_000_000, REF]]):
        await client.post(SYNC)
    assert await _cantidad(db_session) == 5


async def test_sync_frena_si_la_planilla_viene_casi_vacia(client: AsyncClient, db_session: AsyncSession):
    with _sheet(FILAS):
        await client.post(SYNC)
    with _sheet(FILAS[:2]):  # 1 fila contra 4
        r = await client.post(SYNC)
    assert r.status_code == 200 and r.json()["estado"] == "frenado"
    assert await _cantidad(db_session) == 4
    with _sheet([ENC]):
        assert (await client.post(SYNC)).json()["estado"] == "frenado"


async def test_sync_error_de_lectura_responde_502_y_queda_logueado(client: AsyncClient, db_session: AsyncSession):
    with _sheet(error=RuntimeError("The caller does not have permission")):
        r = await client.post(SYNC)
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "SHEET_SYNC_FALLIDO"
    e = await client.get(SYNC + "/estado")
    assert e.json()["estado"] == "error" and "permission" in e.json()["mensaje"]


async def test_sync_sin_configurar(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_atp_interno_id", "")
    with _sheet(FILAS):
        r = await client.post(SYNC)
    assert r.status_code == 502


async def test_sync_no_loguea_el_referente(client: AsyncClient, db_session: AsyncSession):
    with _sheet(FILAS):
        await client.post(SYNC)
    log = (await db_session.execute(select(AtpInternoSyncLog))).scalar_one()
    assert REF not in (log.anomalias or "") and "OTRA PERSONA" not in (log.anomalias or "")


# ── Tablero ───────────────────────────────────────────────────────────────────


async def test_tablero_provincia(client: AsyncClient):
    with _sheet(FILAS):
        await client.post(SYNC)
    r = await client.get(URL)
    assert r.status_code == 200
    b = r.json()
    assert b["anios"] == [2026]
    k = b["gestion"]["kpis"]
    assert k == {"localidades": 2, "pagos": 4, "monto": 36_000_000.0, "sin_fecha": 1, "monto_sin_fecha": 1_000_000.0}
    assio = b["por_anio"][0]["periodo"]
    assert assio["mensual"][0] == 10_000_000 and assio["mensual"][9] == 25_000_000
    assert b["gestion"]["mensual"] == []
    assert [d["departamento"] for d in b["gestion"]["por_departamento"]] == ["PUNILLA", "CALAMUCHITA"]
    emb = next(l for l in b["gestion"]["por_localidad"] if l["codigo_indec"] == "142007")
    assert (emb["pagos"], emb["monto"], emb["ultimo_pago"]) == (2, 15_000_000.0, "2026-10-05")
    assert b["pagos"][-1]["fecha"] is None  # la fecha rota va al final
    assert b["saldo_disponible"] is None
    assert b["estado_sincronizacion"] == "ok"


async def test_tablero_nunca_devuelve_el_referente(client: AsyncClient):
    with _sheet(FILAS):
        await client.post(SYNC)
    for url in (URL, "/internal/atp-interno/por-localidad?anio=2026"):
        texto = (await client.get(url)).text
        assert "referente" not in texto.lower() and REF not in texto and "OTRA PERSONA" not in texto


async def test_tablero_filtra_por_codigo(client: AsyncClient):
    with _sheet(FILAS):
        await client.post(SYNC)
    b = (await client.get(URL, params={"codigo_indec": ["140105"]})).json()
    assert b["gestion"]["kpis"]["pagos"] == 2
    assert {p["codigo_indec"] for p in b["pagos"]} == {"140105"}


async def test_tablero_sin_datos(client: AsyncClient):
    b = (await client.get(URL)).json()
    assert b["gestion"] is None and b["anios"] == [] and b["estado_sincronizacion"] == "sin_datos"


@pytest.mark.parametrize("user", [OPERADOR_USER, CONSULTA_USER])
async def test_tablero_solo_admin_y_autoridad(client: AsyncClient, as_user, user):
    as_user(user)
    assert (await client.get(URL)).status_code == 403


async def test_tablero_autoridad_sin_secretaria(client: AsyncClient, as_user):
    as_user(AUTORIDAD_SIN_SECRETARIA_USER)
    assert (await client.get(URL)).status_code == 200


async def test_interno_por_localidad(client: AsyncClient):
    with _sheet(FILAS):
        await client.post(SYNC)
    r = await client.get("/internal/atp-interno/por-localidad", params={"anio": 2026})
    assert r.json() == [
        {"codigo_indec": "140105", "pagos": 2, "monto": 21_000_000.0},
        {"codigo_indec": "142007", "pagos": 2, "monto": 15_000_000.0},
    ]
    assert (await client.get("/internal/atp-interno/por-localidad", params={"anio": 2025})).json() == []
