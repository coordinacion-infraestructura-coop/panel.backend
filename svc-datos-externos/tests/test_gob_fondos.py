"""Fase 3: planillas de fondos de Gobierno (spec-datos-externos-fase3-fondos.md §7)."""
from datetime import date
from unittest.mock import patch

from httpx import AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_fondos import parse
from app.gob_fondos.models import (
    ExtGobCregCuota,
    ExtGobFondoAmbiental,
    ExtGobFondoValor,
    ExtGobFpermEtapa,
    ExtGobFpermLocalidad,
    ExtGobFpermPrestamo,
)
from app.gob_transferencias import sync as gsync
from app.gobierno.models import ExtGobEnte, ExtGobLocalidad, ExtGobSyncLog
from tests.conftest import CONSULTA_USER

SYNC = "/internal/datos-externos/gobierno/transferencias/sync"
URL = "/api/v1/datos-externos/tablero/transferencias"
NOMBRE_SENSIBLE = "PERSONA CENTINELA"

# ── Parseo puro ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,esperado", [
    (49, (49, 49)), ("49 a 50", (49, 50)), ("49 y 50", (49, 50)), ("48 (b) a 50", (48, 50)),
    ("51 (a)", (51, 51)), ("49 A 51", (49, 51)), ("", (None, None)),
])
def test_etapas(raw, esperado):
    assert parse.etapas(raw) == esperado


@pytest.mark.parametrize("raw,esperado", [
    (45000, date(2023, 3, 15)), ("30 de enero de 2025", date(2025, 1, 30)), ("07 de diciembre de 2023", date(2023, 12, 7)),
    ("28-dic-2023", date(2023, 12, 28)), ("3-ene-24", date(2024, 1, 3)), ("16/7/2024", date(2024, 7, 16)),
    ("cualquier cosa", None), ("", None),
])
def test_fecha_texto(raw, esperado):
    assert parse.fecha_texto(raw) == esperado


def test_columnas_sensibles_y_rangos():
    head = ["ID_LOC", "ETAPAS", "INTENDENTE", "ORD./RES.", "Observaciones ", "CUIT", "MONTO"]
    rangos, tramos = gsync.rangos_sin_sensibles("IMPORT_Listo", head)
    assert rangos == ["'IMPORT_Listo'!A1:B", "'IMPORT_Listo'!D1:D", "'IMPORT_Listo'!G1:G"]
    assert tramos == [[0, 1], [3], [6]]
    assert gsync.columna_a1(25) == "Z" and gsync.columna_a1(26) == "AA" and gsync.columna_a1(70) == "BS"


HEAD_FP = ["ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "ULTIMA CUOTA", "MONTO", "ULT_C_SOC", "AULT_C_S"]
HEAD_CUOTAS = ["ID_LOC", "LOCALIDAD", "CUOTA", "MONTO", "ID_FP"]
HEAD_LISTO = ["ID_LOC", "ETAPAS", "DEPARTAMENTO", "LOCALIDAD", "FECHA", "COPA DESC.", "MONTO TOTAL", "CUOTA", "PLAZO",
              "INTENDENTE", "ORD./RES.", "STICKER", "FECHA INGRESO", "DESTINO DEL PRÉSTAMO"]
HEAD_FA = ["ID_DPTO", "ID_LOC", "DEPARTAMENTO", "LOCALIDAD", "N° EXPEDIENTE", "AÑO", "N° DE CONVENIO", "FECHA DE CONVENIO",
           "N° DE RESOLUCIÓN", "FECHA DE RESOLUCION", "OBJETO SEGÚN CONVENIO (GLOSARIO)", "MONTO", "ESTADO", "FECHA ESTADO",
           "OBSERVACIONES", "INGRESOS", "ORDEN"]
HEAD_CR = ["TIPO", "ID_DPTO", "ID_LOC", "DEPARTAMENTO", "LOCALIDAD", "CUIT", "AÑO", "N° EXPEDIENTE", "DESTINO", "MONTO", "CUOTA",
           "MONTO CUOTA", "ESTADO", "FECHA PAGO CUOTA", "N° RESOLUCIÓN", "FECHA RENDICIÓN CUOTA", "OBSERVACIONES"]

FP = [HEAD_FP, [0, "ULTIMA DISPONIBLE", "-", 55, "-", "-", "-"],
      [140001, "L1", "D1", 55, 0, 1, 0], [140002, "L2", "D1", 54, 300, 0, 1], [140003, "L3", "D2", 53, 500, 0, 0],
      [0, "Disponible", "", "", 9000, "", ""]]
CUOTAS = [HEAD_CUOTAS, [140002, "L2", 55, 300, 2], [140003, "L3", 54, 200, 3], [140003, "L3", 55, 300, 3],
          [140003, "L3", 55, 300, 3]]  # repetida idéntica
LISTO = [HEAD_LISTO,
         [140001, "54 a 55", "D1", "L1", 45291, "enero", 3600, 100, 36, NOMBRE_SENSIBLE, "1/2024", 111, "12 de diciembre de 2023", "Pago de haberes"],
         [140002, 54, "D1", "L2", 45600, "marco", 720, 20, 36, NOMBRE_SENSIBLE, "2/2024", 222, 45500, "Obras"],
         ["", "53", "D2", "L3", 45650, "marzo\nmarzo", 360, 10, 36, NOMBRE_SENSIBLE, "", "", "", "Sin código"],
         [140003, "55", "D2", "L3", "", "", 1080, 30, 36, NOMBRE_SENSIBLE, "3/2025", 333, 45700, "Listo para pagar"]]
FA = [HEAD_FA,
      [1, 140001, "D1", "L1", "0423-1/2024", 2024, "N° 1", 45500, "R-1", "20/8/2024", "CHIPEADORA (21)", 1000, "PAGADO", 45600, NOMBRE_SENSIBLE, 5000, 4],
      [1, 140002, "D1", "L2", "0423-2/2025", 2025, "N° 2", 45700, "R-2", "", "PRENSA HIDRÁULICA", 2000, "LISTO PARA PAGAR", 45710, "", 2500, 4],
      [1, 428, "D1", "COMUNIDAD REGIONAL - D1", "0423-3/2025", 2025, "N° 3", 45700, "R-3", "", "Prensa hidraulica (70)", 3000, "PAGADO", 45720, "", "", 4]]
CR = [HEAD_CR,
      ["Funcionamiento", 1, 428, "D1", "CR D1", 30123456789, 2025, "0931-1/2025", 45000, 100, 100, 50, "PAGADO RENDIDO", 45600, 1, 45800, NOMBRE_SENSIBLE],
      ["Funcionamiento", 1, 428, "D1", "CR D1", 30123456789, 2025, "0931-1/2025", 45000, 100, 2, 50, "ANULADO", "", "", "", ""],
      ["Obras", 2, 429, "D2", "CR D2", 30123456789, 2025, "0931-2/2025", "CAMION CISTERNA", 1000, 1, 600, "LISTO PARA PAGAR", "", "", "", ""],
      ["Funcionamiento", 2, 429, "D2", "CR D2", "", 2026, "", "", "", "", "", "", "", "", "", ""]]  # relleno
CONTROL = [["Año", "Total", "Funcionamiento", "Obras", "Saldo Funcionamiento", "Saldo Obras"],
           [2025, 1300, 300, 1000, 0, 0], [2026, 500, 500, 0, 0, 0], ["", "", "", "", 1, 1]]


def test_parsear_fondo_permanente():
    filas, anom = parse.parsear_fperm_localidad(FP)
    assert [f["codigo_indec"] for f in filas] == ["140001", "140002", "140003"] and not anom
    assert filas[0]["recibio_ultima"] and filas[1]["recibio_anteultima"] and not filas[2]["recibio_ultima"]
    valores, anom = parse.parsear_fperm_valores(FP)
    assert {(v["concepto"], v["monto"]) for v in valores} == {("ultima_etapa_habilitada", 55), ("saldo_cuenta", 9000)} and not anom

    etapas, anom = parse.parsear_fperm_etapas(CUOTAS)
    assert len(etapas) == 3 and anom == [{"tipo": "filas_identicas_unificadas", "cantidad": 1}]

    prestamos, anom = parse.parsear_fperm_prestamos(LISTO)
    assert len(prestamos) == 4
    assert prestamos[0]["fecha"] == date(2023, 12, 31) and prestamos[0]["etapa_desde"] == 54 and prestamos[0]["fecha_ingreso"] == date(2023, 12, 12)
    assert prestamos[1]["mes_inicio_descuento"] is None and prestamos[2]["mes_inicio_descuento"] == 3
    assert prestamos[2]["codigo_indec"] is None and prestamos[3]["fecha"] is None
    assert {"tipo": "valor_invalido", "codigo": "140002", "columna": "COPA DESC."} in anom
    assert {"tipo": "prestamos_sin_codigo", "cantidad": 1} in anom


def test_parsear_fondo_ambiental_y_comunidades():
    filas, anom = parse.parsear_fondo_ambiental(FA)
    assert [(f["codigo_indec"], f["codigo_ente"]) for f in filas] == [("140001", None), ("140002", None), (None, "428")]
    assert filas[0]["fecha_resolucion"] == date(2024, 8, 20) and filas[1]["estado"] == "LISTO PARA PAGAR" and not anom
    ingresos, _ = parse.parsear_fondo_ambiental_ingresos(FA)
    assert [(i["anio"], i["monto"]) for i in ingresos] == [(2024, 5000), (2025, 2500)]

    cuotas, anom = parse.parsear_comunidades_regionales(CR)
    assert len(cuotas) == 3 and cuotas[0]["destino"] is None and cuotas[2]["destino"] == "CAMION CISTERNA"
    assert {"tipo": "filas_de_relleno", "cantidad": 1} in anom and {"tipo": "destino_con_fecha", "cantidad": 2} in anom
    credito, _ = parse.parsear_comunidades_regionales_credito(CONTROL)
    assert {(c["anio"], c["concepto"], c["monto"]) for c in credito} == {
        (2025, "credito_funcionamiento", 300), (2025, "credito_obras", 1000),
        (2026, "credito_funcionamiento", 500), (2026, "credito_obras", 0),
    }


# ── Sync ──────────────────────────────────────────────────────────────────────────

PLANILLAS = {
    ("FP", "FONDO PERM"): FP, ("FP", "FONDO PERM CUOTAS"): CUOTAS, ("FP", "IMPORT_Listo"): LISTO,
    ("FA", "Fondo"): FA, ("CR", "Fondo"): CR, ("CR", "Control"): CONTROL,
}


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_gob_fondo_permanente_id", "FP")
    monkeypatch.setattr(settings, "google_sheet_gob_fondo_ambiental_id", "FA")
    monkeypatch.setattr(settings, "google_sheet_gob_comunidades_regionales_id", "CR")
    monkeypatch.setattr(settings, "gob_transferencias_sync_enabled", True)
    monkeypatch.setattr(gsync, "MIN_LOCALIDADES", 3)


def _parches(planillas: dict | None = None):
    base = dict(PLANILLAS)
    base.update(planillas or {})
    pedidos: list[str] = []

    def pestana_y_cols(rango: str) -> tuple[str, str]:
        pestana, celdas = rango.split("!")
        return pestana.strip("'"), celdas

    async def get_values(sheet_id, rango, render="FORMATTED_VALUE"):
        pedidos.append(rango)
        pestana, celdas = pestana_y_cols(rango)
        valores = base[(sheet_id, pestana)]
        return valores[:1] if celdas == "1:1" else valores

    async def batch_get(sheet_id, rangos, render="FORMATTED_VALUE"):
        out = []
        for rango in rangos:
            pedidos.append(rango)
            pestana, celdas = pestana_y_cols(rango)
            desde, hasta = (gsync_col(x) for x in celdas.replace("1", "").split(":"))
            out.append([fila[desde : hasta + 1] for fila in base[(sheet_id, pestana)]])
        return out

    return (
        patch("app.gob_transferencias.sync.google_sheets.get_values", new=get_values),
        patch("app.gob_transferencias.sync.google_sheets.batch_get_values", new=batch_get),
        pedidos,
    )


def gsync_col(letras: str) -> int:
    n = 0
    for c in letras:
        n = n * 26 + ord(c) - 64
    return n - 1


async def _nomenclador(db: AsyncSession) -> None:
    db.add_all([
        ExtGobLocalidad(codigo_indec="140001", nombre_gob="L1", departamento_gob="D1", tipo="MU", id_geo="g1"),
        ExtGobLocalidad(codigo_indec="140002", nombre_gob="L2", departamento_gob="D1", tipo="CO", id_geo="g2"),
        ExtGobLocalidad(codigo_indec="140003", nombre_gob="L3", departamento_gob="D2", tipo="MU", id_geo="g3"),
        ExtGobEnte(codigo="428", nombre="COMUNIDAD REGIONAL - D1", tipo_ente="comunidad_regional", departamento="D1"),
        ExtGobEnte(codigo="429", nombre="COMUNIDAD REGIONAL - D2", tipo_ente="comunidad_regional", departamento="D2"),
    ])
    await db.commit()


async def _count(db, modelo, *where) -> int:
    return (await db.execute(select(func.count()).select_from(modelo).where(*where))).scalar_one()


FONDOS = ("fondo_permanente", "fondo_ambiental", "comunidades_regionales")


async def _sync(client: AsyncClient, planillas: dict | None = None):
    p1, p2, pedidos = _parches(planillas)
    resultados = {}
    with p1, p2:
        for fuente in FONDOS:
            r = await client.post(SYNC, params={"fuente": fuente})
            resultados[fuente] = r
    return resultados, pedidos


async def test_sync_fondos_sin_leer_columnas_sensibles(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    resultados, pedidos = await _sync(client)
    logs = {f: r.json()[0] for f, r in resultados.items()}
    assert all(r.status_code == 200 for r in resultados.values()), {f: r.text for f, r in resultados.items()}
    assert all(log["estado"] == "ok" for log in logs.values()), logs

    # Nunca se pidió un rango que incluya INTENDENTE, CUIT u OBSERVACIONES.
    assert "'IMPORT_Listo'!A1:CZ" not in pedidos and "'Fondo'!A1:CZ" not in pedidos
    assert "'IMPORT_Listo'!A1:I" in pedidos and "'IMPORT_Listo'!K1:N" in pedidos  # J = INTENDENTE
    assert "'Fondo'!A1:N" in pedidos and "'Fondo'!P1:Q" in pedidos  # O = OBSERVACIONES (Fondo Ambiental)
    todos = (await db_session.execute(select(ExtGobSyncLog))).scalars().all()
    assert NOMBRE_SENSIBLE not in str([x.anomalias for x in todos])
    for modelo in (ExtGobFpermPrestamo, ExtGobFondoAmbiental, ExtGobCregCuota):
        assert NOMBRE_SENSIBLE not in str([vars(x) for x in (await db_session.execute(select(modelo))).scalars()])

    assert await _count(db_session, ExtGobFpermLocalidad) == 3 and await _count(db_session, ExtGobFpermEtapa) == 3
    assert await _count(db_session, ExtGobFpermPrestamo) == 4
    assert await _count(db_session, ExtGobFondoAmbiental) == 3 and await _count(db_session, ExtGobCregCuota) == 3
    assert await _count(db_session, ExtGobFondoValor) == 2 + 2 + 4
    # Control interno: L3 tiene 500 disponible y etapas por 500; L2 300 y 300: cierra.
    assert not any(a.get("tipo") == "control_etapas_vs_disponible" for a in logs["fondo_permanente"]["anomalias"])


async def test_sync_fondos_reemplaza_solo_lo_suyo_y_frena(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    # Las etapas pueden bajar sin frenar; Fondo Ambiental vacío frena y conserva los datos.
    resultados, _ = await _sync(client, {("FP", "FONDO PERM CUOTAS"): CUOTAS[:2], ("FA", "Fondo"): FA[:1]})
    assert resultados["fondo_permanente"].json()[0]["estado"] == "ok"
    assert await _count(db_session, ExtGobFpermEtapa) == 1
    assert resultados["fondo_ambiental"].status_code == 502
    assert await _count(db_session, ExtGobFondoAmbiental) == 3
    # Cada fuente reemplaza solo sus valores sueltos.
    assert await _count(db_session, ExtGobFondoValor, ExtGobFondoValor.fondo == "fondo_ambiental") == 2
    assert await _count(db_session, ExtGobFondoValor, ExtGobFondoValor.fondo == "comunidades_regionales") == 4


# ── Tablero ───────────────────────────────────────────────────────────────────────


async def test_tablero_fondo_permanente(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    d = (await client.get(f"{URL}/fondo-permanente", params={"anio": 2026})).json()
    assert d["ultima_etapa_habilitada"] == 55 and d["saldo_cuenta"] == 9000
    assert d["localidades_adheridas"] == 3 and d["recibieron_ultima"] == 1 and d["recibieron_anteultima"] == 1
    assert d["disponible"] == 800 and d["localidades_con_disponible"] == 2
    assert d["listo_para_pagar"] == {"monto": 1080, "prestamos": 1, "localidades": 1}
    assert d["anios"] == [2024, 2023]
    assert d["gestion"] == {"monto": 3600 + 720 + 360, "prestamos": 3, "localidades": 2}
    a2024 = next(a for a in d["por_anio"] if a["anio"] == 2024)
    assert a2024["otorgado"]["monto"] == 720 + 360 and a2024["mensual"][10] == 720
    l3 = next(x for x in d["localidades"] if x["codigo_indec"] == "140003")
    assert l3["etapas_disponibles"] == [54, 55] and l3["disponible"] == 500

    # Con filtro: sin saldo en cuenta (es del fondo entero) y sin el préstamo sin código.
    f = (await client.get(f"{URL}/fondo-permanente", params={"anio": 2026, "codigo_indec": ["140003"]})).json()
    assert f["saldo_cuenta"] is None and f["localidades_adheridas"] == 1 and f["gestion"]["prestamos"] == 0


async def test_tablero_fondo_ambiental(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    d = (await client.get(f"{URL}/fondo-ambiental", params={"anio": 2026})).json()
    g = d["gestion"]
    assert g["localidades"] == 2 and g["entes"] == 1 and g["afectado"] == 6000 and g["pagado"] == 4000
    assert g["ingresos"] == 7500 and g["disponible"] == 1500
    estados = {e["estado"]: e for e in g["estados"]}
    assert estados["TRIBUNAL DE CUENTAS"]["cantidad"] == 0 and estados["PAGADO"]["monto"] == 4000
    a2025 = next(a for a in d["por_anio"] if a["anio"] == 2025)["kpis"]
    assert a2025["afectado"] == 5000 and a2025["ingresos"] == 2500 and a2025["disponible"] == -2500
    # Las variantes de "prensa hidráulica" se agrupan.
    assert d["objetos"][0] == {"objeto": "PRENSA HIDRAULICA", "cantidad": 2, "monto": 5000}
    ente = next(c for c in d["convenios"] if c["es_ente"])
    assert ente["localidad"] == "COMUNIDAD REGIONAL - D1"

    # Filtro por una localidad de D2: no entra el ente de D1 ni los ingresos.
    f = (await client.get(f"{URL}/fondo-ambiental", params={"anio": 2026, "codigo_indec": ["140001"]})).json()
    assert f["gestion"]["afectado"] == 4000 and f["gestion"]["entes"] == 1 and f["gestion"]["ingresos"] is None
    f = (await client.get(f"{URL}/fondo-ambiental", params={"anio": 2026, "codigo_indec": ["140003"]})).json()
    assert f["gestion"] is None and f["convenios"] == []


async def test_tablero_comunidades_regionales(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    d = (await client.get(f"{URL}/comunidades-regionales", params={"anio": 2026})).json()
    assert d["departamentos"] is None and d["anios"] == [2026, 2025]
    k = next(a for a in d["por_anio"] if a["anio"] == 2025)["kpis"]
    # Funcionamiento: una cuota pagada (50), la anulada no cuenta.
    assert k["funcionamiento"] == {"credito": 300, "cuotas": 1, "monto_cuotas": 50, "pagado": 50, "a_pagar": 0, "saldo": 250}
    assert k["obras"] == {"credito": 1000, "cuotas": 1, "monto_cuotas": 600, "pagado": 0, "a_pagar": 600, "saldo": 400}
    assert k["comunidades"] == 2 and {e["estado"] for e in k["estados"]} == {"PAGADO RENDIDO", "ANULADO", "LISTO PARA PAGAR"}
    k2026 = next(a for a in d["por_anio"] if a["anio"] == 2026)["kpis"]
    assert k2026["funcionamiento"]["credito"] == 500 and k2026["funcionamiento"]["cuotas"] == 0

    f = (await client.get(f"{URL}/comunidades-regionales", params={"anio": 2026, "codigo_indec": ["140003"]})).json()
    assert f["departamentos"] == ["D2"] and {c["codigo_ente"] for c in f["cuotas"]} == {"429"}
    assert f["gestion"]["obras"]["credito"] is None


async def test_resumen_suma_fondo_ambiental_pagado_a_localidades(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    d = (await client.get(f"{URL}/resumen", params={"anio": 2024})).json()
    assert d["total"]["fondo_ambiental"] == 1000 and d["total"]["total"] == 1000
    # 2025: lo pagado fue al ente (no entra) y lo de L2 está listo para pagar (no entra).
    d = (await client.get(f"{URL}/resumen", params={"anio": 2025})).json()
    assert d["total"]["fondo_ambiental"] == 0


async def test_fondos_solo_admin_y_autoridad(client: AsyncClient, as_user):
    as_user(CONSULTA_USER)
    for s in ("fondo-permanente", "fondo-ambiental", "comunidades-regionales"):
        assert (await client.get(f"{URL}/{s}", params={"anio": 2026})).status_code == 403
