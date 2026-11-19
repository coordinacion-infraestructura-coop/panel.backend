"""Planilla "Gobierno" de la Privada del Gobernador: anuncios, FOCOM y ATP histórico
(spec-datos-externos-privada-gobernador.md §8)."""
from datetime import date
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_privada import parse
from app.gob_privada.models import ExtGobAnuncio, ExtGobAtpHistorico, ExtGobFocom
from app.gob_transferencias import sync as gsync
from app.gobierno.models import ExtGobLocalidad, ExtGobSyncLog
from tests.conftest import CONSULTA_USER

SYNC = "/internal/datos-externos/gobierno/transferencias/sync"
URL = "/api/v1/datos-externos/tablero/transferencias"
SENSIBLE = "PERSONA CENTINELA"
SHEET = "PRIV"
FUENTES = ("anuncios_gobernador", "focom", "atp_historico")


def serial(d: date) -> int:
    """Fecha como la devuelve Sheets con `UNFORMATTED_VALUE`."""
    return (d - date(1899, 12, 30)).days


# ── Planilla de prueba ──────────────────────────────────────────────────────────────

GOBIERNO = [
    ["ascasu", "Fecha de carga del anuncio", "Fuente del anuncio", "Fecha de anuncio", "Departamento", "Localidad",
     "Ministerio", "Área", "Anuncio", "Detalle del anuncio", "Estado", "Línea base del indicador",
     "Valor actual del indicador", "Grado de cumplimiento", "Responsable", "Fecha de actualizacion", "Comentarios",
     "Indicador de seguimiento Gabriel", "Estado Gabriel", "Coinciden"],
    [45.0, None, "Link ; https://prensa.cba.gov.ar/a", serial(date(2024, 1, 10)), "D1", "L1", "Gobierno", None,
     "El gobernador anunció $56 millones para una ambulancia", None, "Pagado", 0, 100, 1, SENSIBLE, None,
     "HAY UN ATP DE 30 MILLONES", "26-FOCOM", "PAGADO", "SI"],
    [50.0, None, "Link", serial(date(2026, 5, 26)), "D2", "San José", None, None,
     "Aporte de 10 millones para la iglesia", "y otros $1.500.000 para el club", "Pendiente", None, None, "50,00%",
     SENSIBLE, None, None, 120.0, "#N/A", "NO"],
    # Typo de año: la fecha se descarta y queda el texto.
    [51.0, None, None, serial(date(2016, 3, 1)), "D9", "Comunidad regional", None, None, "Anuncio sin monto", None,
     None, None, None, None, None, None, None, None, None, None],
    [45.0, None, None, serial(date(2024, 1, 10)), "D1", "L1", None, None, "repetido", None, "Pagado",
     None, None, None, None, None, None, None, None, None],
]

FOCOM = [
    ["ID_FOCOM", "EXPTE N°", "N° CONVENIO", "FECHA CONVENIO", "N° RESOLUCIÓN", "DEPARTAMENTO", "TIPO", "ID_LOC",
     "LOCALIDAD", "MONTO", "CONCEPTO", "CATEGORÍA", "ESTADO", "FECHA PAGO", "COMPUTO PLAZO VISACIÓN",
     "ADMINISTRATIVO ASIGNADO", "COORDINADOR ASIGNADO", "REFERENTE POLITICO", "OBSERVACIONES",
     "OBSERVACIONES -\nENCARGADO", "AÑO", "ESTADO OBRA"],
    ["1-FOCOM", "0423-1/2024", "N° 52", serial(date(2024, 7, 16)), "158/2024", "D1", "MUNICIPIO", 140001, "L1",
     30000000, "PLAZA", "PLAZAS Y ESPACIOS VERDES", "PAGADO", serial(date(2024, 10, 10)), "VISADO 19/8",
     SENSIBLE, SENSIBLE, SENSIBLE, SENSIBLE, SENSIBLE, 2024, "EN PROCESO"],
    ["2-FOCOM", "0423-2/2024", "N° 101", serial(date(2024, 7, 25)), serial(date(2024, 8, 1)), "D1", "COMUNA", 140002,
     "L2", 60000000, "CORDÓN CUNETA", "VIAL URBANA", "Pagado ATP", None, None,
     SENSIBLE, SENSIBLE, SENSIBLE, None, None, 2024, "TERMINADA"],
    ["3-FOCOM", None, None, None, None, "D2", "MUNICIPIO", 140003, "L3", 20000000, "AGUA", "AGUA", "PENDIENTE ATP",
     None, None, None, None, SENSIBLE, None, None, 2025, "#N/A"],
    # La planilla trae el ID precargado en filas vacías.
    ["4-FOCOM"] + [None] * 21,
    ["5-FOCOM"] + [None] * 21,
]

ATP = [
    ["ID ATP", "DEPARTAMENTO", "LOCALIDAD", "FECHA (TRANSFERENCIA):", " MONTO TRANSFERENCIA:", " REFERENTE",
     None, None, None, None, "Tabla de coincidencias"],
    ["1-ATP", "D1", "L1", serial(date(2023, 12, 28)), 1500000, SENSIBLE, None, None, None, None, f"Pagado-{SENSIBLE}"],
    ["2-ATP", "D2", "SAN JOSÉ", serial(date(2024, 3, 1)), 30000000, SENSIBLE],
    ["1782,-ATP", "MAL DEPTO", "L3", serial(date(2025, 6, 1)), 750000, SENSIBLE],
    ["2-ATP", "D1", "L2", serial(date(2025, 7, 1)), 500000, SENSIBLE],  # ID repetido
    # 2026 sale de ATP Interno: no se guarda, se usa para el control.
    ["9-ATP", "D1", "L1", serial(date(2026, 1, 7)), 4000000, SENSIBLE],
    ["10-ATP", "D2", "L3", serial(date(2026, 2, 7)), 6000000, SENSIBLE],
    ["11-ATP", "D2", "L3", "sin fecha", 6000000, SENSIBLE],
]

PLANILLAS = {(SHEET, "Gobierno"): GOBIERNO, (SHEET, "FOCOM"): FOCOM, (SHEET, "ATP"): ATP}


def _col(letras: str) -> int:
    n = 0
    for c in letras:
        n = n * 26 + ord(c) - 64
    return n - 1


def _parches(planillas: dict | None = None):
    base = dict(PLANILLAS)
    base.update(planillas or {})
    pedidos: list[str] = []

    def partes(rango: str) -> tuple[str, str]:
        pestana, celdas = rango.split("!")
        return pestana.strip("'"), celdas

    async def get_values(sheet_id, rango, render="FORMATTED_VALUE"):
        pedidos.append(rango)
        pestana, celdas = partes(rango)
        valores = base[(sheet_id, pestana)]
        return valores[:1] if celdas == "1:1" else valores

    async def batch_get(sheet_id, rangos, render="FORMATTED_VALUE"):
        out = []
        for rango in rangos:
            pedidos.append(rango)
            pestana, celdas = partes(rango)
            desde, hasta = (_col(x) for x in celdas.replace("1", "").split(":"))
            out.append([fila[desde : hasta + 1] for fila in base[(sheet_id, pestana)]])
        return out

    return (
        patch("app.gob_transferencias.sync.google_sheets.get_values", new=get_values),
        patch("app.gob_transferencias.sync.google_sheets.batch_get_values", new=batch_get),
        pedidos,
    )


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_gob_privada_gobernador_id", SHEET)
    monkeypatch.setattr(settings, "gob_transferencias_sync_enabled", True)


async def _nomenclador(db: AsyncSession) -> None:
    db.add_all([
        ExtGobLocalidad(codigo_indec="140001", nombre_gob="L1", departamento_gob="D1", tipo="MU", id_geo="g1"),
        ExtGobLocalidad(codigo_indec="140002", nombre_gob="L2", departamento_gob="D1", tipo="CO", id_geo="g2"),
        ExtGobLocalidad(codigo_indec="140003", nombre_gob="L3", departamento_gob="D2", tipo="MU", id_geo="g3"),
        # Mismo nombre en dos departamentos: solo resuelve con el departamento.
        ExtGobLocalidad(codigo_indec="140004", nombre_gob="San José", departamento_gob="D1", tipo="CO", id_geo="g4"),
        ExtGobLocalidad(codigo_indec="140005", nombre_gob="San José", departamento_gob="D2", tipo="CO", id_geo="g5"),
    ])
    await db.commit()


async def _count(db, modelo) -> int:
    return (await db.execute(select(func.count()).select_from(modelo))).scalar_one()


async def _sync(client: AsyncClient, planillas: dict | None = None, atp_interno: dict | None = None):
    p1, p2, pedidos = _parches(planillas)
    resultados = {}
    atp = AsyncMock(return_value=atp_interno)
    with p1, p2, patch("app.gob_transferencias.sync.atp_interno.atp_por_localidad", new=atp):
        for fuente in FUENTES:
            resultados[fuente] = await client.post(SYNC, params={"fuente": fuente})
    return resultados, pedidos


# ── Parseo puro ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("anunció $56 millones para una ambulancia", [56e6]),
        ("otros 60 millones de pesos y 40 millones más", [60e6, 40e6]),
        ("un aporte de $1.500.000 al club", [1.5e6]),
        ("inversión de $2 mil millones", [2e9]),
        ("1.500 millones para obras", [1.5e9]),
        ("pavimentación de 4 cuadras en 2024", []),
    ],
)
def test_montos_en_texto(texto, esperado):
    assert parse.montos_en_texto(texto) == esperado


@pytest.mark.parametrize(("raw", "esperado"), [(1, 1.0), (0.5, 0.5), (100, 1.0), ("100,00%", 1.0), ("50%", 0.5), ("", None), ("#N/A", None)])
def test_grado(raw, esperado):
    assert parse.grado(raw) == esperado


def test_normalizar_id():
    assert parse.normalizar_id("1782,-ATP", "ATP") == "1782-ATP"
    assert parse.normalizar_id(12.0, "FOCOM") == "12-FOCOM"
    assert parse.normalizar_id(None, "ATP") is None


def test_parsear_anuncios():
    filas, anomalias = parse.parsear_anuncios(GOBIERNO, hoy=date(2026, 11, 19))
    por_id = {f["ascasu"]: f for f in filas}
    assert sorted(por_id) == [45, 50, 51]
    assert {"tipo": "fila_repetida", "codigo": "45"} in anomalias
    a = por_id[45]
    assert a["fuente_url"] == "https://prensa.cba.gov.ar/a" and a["montos_mencionados"] == [56e6]
    assert a["indicador_seguimiento"] == "26-FOCOM" and a["coinciden"] is True and a["grado_cumplimiento"] == 1
    b = por_id[50]
    assert b["indicador_seguimiento"] == "120" and b["estado_seguimiento"] is None and b["grado_cumplimiento"] == 0.5
    assert b["montos_mencionados"] == [10e6, 1.5e6] and b["fuente_url"] is None
    c = por_id[51]
    assert c["fecha_anuncio"] is None and c["fecha_anuncio_texto"] == "2016-03-01"
    assert {"tipo": "fecha_fuera_de_rango", "cantidad": 1} in anomalias
    assert len({f["hash_contenido"] for f in filas}) == 3


def test_parsear_focom_y_atp():
    filas, anomalias = parse.parsear_focom(FOCOM)
    assert [f["id_focom"] for f in filas] == ["1-FOCOM", "2-FOCOM", "3-FOCOM"]
    assert [f["estado"] for f in filas] == ["PAGADO", "PAGADO ATP", "PENDIENTE ATP"]
    assert filas[1]["resolucion"] is None  # vino convertida en fecha
    assert filas[2]["estado_obra"] is None and filas[0]["codigo_indec"] == "140001"
    assert {"tipo": "filas_sin_datos", "cantidad": 2} in anomalias

    filas, anomalias = parse.parsear_atp_historico(ATP)
    assert [(f["id_atp"], f["ocurrencia"]) for f in filas] == [("1-ATP", 1), ("2-ATP", 1), ("1782-ATP", 1), ("2-ATP", 2)]
    assert all(f["fecha"] < parse.CORTE_ATP_INTERNO for f in filas)
    assert {"tipo": "atp_desde_corte", "corte": "2026-01-01", "filas": 2, "monto": 10000000.0} in anomalias
    assert {"tipo": "id_repetido", "codigos": ["2-ATP"]} in anomalias
    assert {"tipo": "fila_invalida", "fila": 8} in anomalias


# ── Sync ────────────────────────────────────────────────────────────────────────────


async def test_sync_sin_leer_columnas_de_personas(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    resultados, pedidos = await _sync(client, atp_interno={"140001": 4000000.0, "140003": 6000000.0})
    assert all(r.status_code == 200 for r in resultados.values()), {f: r.text for f, r in resultados.items()}

    # Nunca se pidió un rango con Responsable (O), las columnas P–T de FOCOM ni F y K de ATP.
    assert not any(p.endswith("A1:CZ") for p in pedidos)
    assert "'Gobierno'!A1:N" in pedidos and "'Gobierno'!P1:T" in pedidos
    assert "'FOCOM'!A1:O" in pedidos and "'FOCOM'!U1:V" in pedidos
    assert "'ATP'!A1:E" in pedidos and "'ATP'!G1:J" in pedidos and not any(p.startswith("'ATP'!K") for p in pedidos)
    for modelo in (ExtGobAnuncio, ExtGobFocom, ExtGobAtpHistorico, ExtGobSyncLog):
        assert SENSIBLE not in str([vars(x) for x in (await db_session.execute(select(modelo))).scalars()])

    assert await _count(db_session, ExtGobAnuncio) == 3
    assert await _count(db_session, ExtGobFocom) == 3
    assert await _count(db_session, ExtGobAtpHistorico) == 4


async def test_sync_resuelve_localidades_y_controla_atp_interno(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    resultados, _ = await _sync(client, atp_interno={"140001": 4000000.0, "140003": 6000000.0})

    anuncios = {a.ascasu: a.codigo_indec for a in (await db_session.execute(select(ExtGobAnuncio))).scalars()}
    assert anuncios == {45: "140001", 50: "140005", 51: None}
    atp = {(a.id_atp, a.ocurrencia): a.codigo_indec for a in (await db_session.execute(select(ExtGobAtpHistorico))).scalars()}
    # SAN JOSÉ de D2 por departamento; L3 con el departamento mal, por nombre único.
    assert atp == {("1-ATP", 1): "140001", ("2-ATP", 1): "140005", ("1782-ATP", 1): "140003", ("2-ATP", 2): "140002"}

    log_anuncios = resultados["anuncios_gobernador"].json()[0]
    assert {"tipo": "localidad_sin_codigo", "cantidad": 1, "localidades": ["Comunidad regional"]} in log_anuncios["anomalias"]
    control = next(a for a in resultados["atp_historico"].json()[0]["anomalias"] if a["tipo"] == "control_atp_interno")
    assert control["resultado"] == "coincide" and control["diferencia"] == 0


async def test_control_atp_interno_avisa_diferencia_sin_frenar(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    resultados, _ = await _sync(client, atp_interno={"140001": 4000000.0})
    log = resultados["atp_historico"].json()[0]
    assert log["estado"] in ("ok", "parcial")
    control = next(a for a in log["anomalias"] if a["tipo"] == "control_atp_interno")
    assert control["resultado"] == "difiere" and control["diferencia"] == 6000000.0
    assert await _count(db_session, ExtGobAtpHistorico) == 4

    resultados, _ = await _sync(client, atp_interno=None)
    control = next(a for a in resultados["atp_historico"].json()[0]["anomalias"] if a["tipo"] == "control_atp_interno")
    assert control["resultado"] == "atp_interno_no_disponible"


async def test_sync_frena_si_la_pestana_viene_vacia(client: AsyncClient, db_session: AsyncSession):
    """Si el IMPORTRANGE falla (pestaña vacía o `#REF!`) se conserva el histórico cargado."""
    await _nomenclador(db_session)
    await _sync(client, atp_interno={})
    resultados, _ = await _sync(client, {(SHEET, "ATP"): ATP[:1], (SHEET, "FOCOM"): FOCOM[:1]}, atp_interno={})
    assert resultados["atp_historico"].status_code == 502 and resultados["focom"].status_code == 502
    assert await _count(db_session, ExtGobAtpHistorico) == 4 and await _count(db_session, ExtGobFocom) == 3


# ── Tablero ─────────────────────────────────────────────────────────────────────────


async def test_tablero_focom(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client, atp_interno={})
    r = await client.get(f"{URL}/focom", params={"anio": 2026})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["concepto"] == "focom" and d["anios"] == [2025, 2024]
    g = d["gestion"]
    assert g["convenios"] == 3 and g["localidades"] == 3 and g["monto"] == 110000000
    # FOCOM puro aparte de lo que se pagó o se paga por ATP.
    assert (g["puro"], g["convenios_puro"], g["pagado_atp"], g["pendiente_atp"]) == (30000000, 1, 60000000, 20000000)
    assert [e["estado"] for e in g["estados"]] == ["PAGADO", "PAGADO ATP", "PENDIENTE ATP"]
    assert g["categorias"][0] == {"objeto": "VIAL URBANA", "cantidad": 1, "monto": 60000000}
    assert {"estado": "SIN DATO", "cantidad": 1} in g["estados_obra"]
    assert {a["anio"]: a["kpis"]["convenios"] for a in d["por_anio"]} == {2025: 1, 2024: 2}
    assert d["convenios"][0]["id_focom"] == "3-FOCOM" and d["convenios"][0]["localidad"] == "L3"

    r = await client.get(f"{URL}/focom", params={"anio": 2026, "codigo_indec": ["140002"]})
    g = r.json()["gestion"]
    assert g["convenios"] == 1 and g["puro"] == 0 and g["pagado_atp"] == 60000000


async def test_tablero_focom_sin_datos_y_roles(client: AsyncClient, as_user):
    r = await client.get(f"{URL}/focom", params={"anio": 2026})
    assert r.status_code == 200 and r.json()["gestion"] is None
    as_user(CONSULTA_USER)
    assert (await client.get(f"{URL}/focom", params={"anio": 2026})).status_code == 403


async def test_tablero_atp_historico(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    r = await client.get(f"{URL}/atp-historico", params={"anio": 2026})
    assert r.status_code == 200 and r.json()["gestion"] is None and r.json()["estado_sincronizacion"] == "sin_datos"

    await _sync(client, atp_interno={})
    d = (await client.get(f"{URL}/atp-historico", params={"anio": 2026})).json()
    # Misma forma que ATP Interno, sin años desde el corte y sin referente.
    assert d["corte"] == "2026-01-01" and d["anios"] == [2023, 2024, 2025]
    assert d["gestion"]["kpis"] == {"localidades": 4, "pagos": 4, "monto": 32750000.0, "sin_fecha": 0, "monto_sin_fecha": 0.0}
    anio_2025 = next(a["periodo"] for a in d["por_anio"] if a["anio"] == 2025)
    assert anio_2025["mensual"][5] == 750000 and anio_2025["mensual"][6] == 500000
    assert {p["localidad"] for p in d["pagos"]} == {"L1", "San José", "L3", "L2"}
    assert SENSIBLE not in r.text + str(d)

    d = (await client.get(f"{URL}/atp-historico", params={"anio": 2026, "codigo_indec": ["140005"]})).json()
    assert d["gestion"]["kpis"]["monto"] == 30000000 and d["pagos"][0]["departamento"] == "D2"


async def test_resumen_usa_atp_historico_antes_de_2026(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client, atp_interno={})
    interno = AsyncMock(return_value={"140001": 99.0})
    with patch("app.tablero.service.atp_interno.atp_por_localidad", new=interno):
        r2025 = (await client.get(f"{URL}/resumen", params={"anio": 2025})).json()
        r2026 = (await client.get(f"{URL}/resumen", params={"anio": 2026})).json()
    assert r2025["atp_disponible"] and r2025["total"]["atp"] == 1250000  # L3 750.000 + L2 500.000
    interno.assert_awaited_once_with(2026)
    assert r2026["total"]["atp"] == 99.0
