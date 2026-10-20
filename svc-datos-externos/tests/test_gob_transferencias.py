"""Planillas de transferencias de Gobierno: parseo puro, sync y conciliación
(spec-datos-externos-fase2-transferencias.md §9). La planilla va siempre mockeada."""
import json
from datetime import date
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_transferencias import conciliacion, parse
from app.gob_transferencias import sync as gsync
from app.gob_transferencias.models import (
    ExtGobCopa,
    ExtGobEmpleados,
    ExtGobFodemep,
    ExtGobFodemepEstado,
    ExtGobFofindes,
    ExtGobFommep,
)
from app.gobierno.models import ExtGobLocalidad, ExtGobSyncLog
from app.transferencias.models import ExtTransferencia

# Fechas como número de serie de Sheets
ENE_2025 = 45658  # 2025-01-01
DIC_2024_30 = 45656  # 2024-12-30
ENE_2025_10 = 45667  # 2025-01-10
OCT_2023 = 45200  # 2023-10-01

MASA_CENTINELA = 987654.32

HEAD_COPA = [
    "ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "ULT", "MES_order", "COMPLETO", "ULT_COMP", "Quincena", "Mes", "Año",
    "Fecha de Pago", "CODIGO", "NOMBRE", "INDICE", "Total COP. MUNICIPIOS", "AJUSTE", "TOTAL AJUSTADO",
    "NETO RESULTANTE", "NETO A TRANSFERIR", "Caja de Jubilaciones", "APROSS", "Redes Gas", "Redes Gas", "Varios",
    "Municipio", "Departamento",
]


def fila_copa(codigo, quincena="1°", mes=ENE_2025, anio=2025, bruto=1000.0, caja=100.0, apross=50.0):
    neto = bruto - caja - apross - 10 - 5
    return [codigo, "LOC", "DEP", 0, 1, 1, 0, quincena, mes, anio, ENE_2025 + 20, 7, "MUNICIPALIDAD", 0.001,
            bruto, "", "", neto, max(neto, 0), caja, apross, 10, 5, 0, "LOC", "DEP"]


def test_parse_copa_mes_serial_quincena_y_descuentos():
    filas, anomalias = parse.parsear_copa([HEAD_COPA, fila_copa("140001"), fila_copa("140001", quincena="2°")])
    assert [(f["anio"], f["mes"], f["quincena"]) for f in filas] == [(2025, 1, 1), (2025, 1, 2)]
    f = filas[0]
    assert f["bruto"] == 1000 and f["caja_jubilaciones"] == 100 and f["apross"] == 50
    assert f["fecha_pago"] == date(2025, 1, 21)
    # Encabezado repetido: no pisa al primero.
    assert f["descuentos"] == {"Caja de Jubilaciones": 100, "APROSS": 50, "Redes Gas": 10, "Redes Gas (2)": 5, "Varios": 0}
    assert anomalias == []


def test_parse_copa_mes_serial_de_otro_anio_toma_solo_el_mes():
    # `Mes` trae una fecha de 2026 con formato de mes; el año sale de `Año`.
    filas, _ = parse.parsear_copa([HEAD_COPA, fila_copa("140001", mes=46368, anio=2025)])  # 2026-12-12
    assert (filas[0]["anio"], filas[0]["mes"]) == (2025, 12)


def test_parse_copa_errores_de_celda_y_filas_invalidas():
    mala = fila_copa("140002")
    mala[HEAD_COPA.index("Redes Gas")] = "#############"
    sin_mes = fila_copa("140003", mes="")
    filas, anomalias = parse.parsear_copa([HEAD_COPA, mala, sin_mes, fila_copa(""), fila_copa("140002")])
    assert len(filas) == 1 and filas[0]["descuentos"]["Redes Gas"] == 0
    tipos = sorted(a["tipo"] for a in anomalias)
    assert tipos == ["fila_invalida", "fila_repetida", "fila_sin_codigo", "valor_invalido"]
    assert {"tipo": "valor_invalido", "codigo": "140002", "columna": "Redes Gas"} in anomalias


def test_parse_copa_columna_de_descuento_nueva_entra_sin_cambiar_codigo():
    head = HEAD_COPA[:21] + ["Descuento Nuevo"] + HEAD_COPA[21:]
    fila = fila_copa("140001")
    fila = fila[:21] + [7] + fila[21:]
    filas, _ = parse.parsear_copa([head, fila])
    assert filas[0]["descuentos"]["Descuento Nuevo"] == 7


def test_parse_copa_falta_encabezado_obligatorio():
    with pytest.raises(parse.EstructuraInvalida):
        parse.parsear_copa([[h for h in HEAD_COPA if h != "APROSS"]])


HEAD_FOF = [
    "ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "ULT", "CODIGO", "NOMBRE", "INDICE", "Total Parte VariableFOFINDES",
    "Excedente 30%", "Excedente 70%", "FOFINDES", "Bomberos Voluntarios Río Tercero", "Aportes Reintegrables - FOFINDES",
    "NETO RESULTANTE", "NETO A TRANSFERIR", "Bomberos Voluntarios Río Tercero", "Aportes Reintegrables - FOFINDES",
    "Fecha de Pago", "MES", "AÑO", "MUNICIPIO/COMUNA", "DEPARTAMENTO 1", "MUN-COM",
]


def fila_fof(codigo, fecha=ENE_2025 + 40, mes=ENE_2025, anio=2025, bruto=200.0):
    return [codigo, "LOC", "DEP", 0, 7, "MUNI", 0.1, bruto, 0, 0, bruto, 3, 2, bruto - 5, bruto - 5, 999, 999,
            fecha, mes, anio, "LOC", "DEP", "MUNICIPIO"]


def test_parse_fofindes_dos_pagos_en_el_mismo_mes_y_descuentos_sin_repetidos():
    filas, anomalias = parse.parsear_fofindes([
        HEAD_FOF,
        fila_fof("140001", fecha=DIC_2024_30, mes=46003, anio=2024),
        fila_fof("140001", fecha=ENE_2025_10, mes=46003, anio=2024),
    ])
    assert len(filas) == 2 and {f["mes"] for f in filas} == {12}
    assert {f["fecha_pago"] for f in filas} == {date(2024, 12, 30), date(2025, 1, 10)}
    # Solo los descuentos entre FOFINDES y el neto; las columnas repetidas de después no.
    assert filas[0]["descuentos"] == {"Bomberos Voluntarios Río Tercero": 3, "Aportes Reintegrables - FOFINDES": 2}
    assert anomalias == []


HEAD_FODEMEP = ["ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "ULT", "CODIGO", "NOMBRE", "INDICE", "Total FODEEMEP",
                "ACUMULADO", "NETO A TRANSFERIR", "Fecha de Pago", "MES", "AÑO", "MUNICIPIO/COMUNA", "DEPARTAMENTO_COPA", "MUN-COM"]


def test_parse_fodemep_periodo_con_anio_propio_y_presupuestado_vacio():
    filas, _ = parse.parsear_fodemep([
        HEAD_FODEMEP,
        ["140001", "L", "D", 0, 1, "", "", "", "", 500, OCT_2023 + 72, OCT_2023, 2023, "L", "D"],
        ["140001", "L", "D", 0, 1, "M", 0.1, 600, 100, 500, ENE_2025 + 5, "enero 2025", 2025, "L", "D", "MUNICIPIO"],
    ])
    assert filas[0]["periodo"] == date(2023, 10, 1) and filas[0]["presupuestado"] is None
    assert filas[1]["periodo"] == date(2025, 1, 1) and filas[1]["acumulado"] == 100


def test_parse_empleados_na_es_sin_dato_y_las_anomalias_no_llevan_valores():
    head = ["ID_LOC", "LOCALIDADES", "ID_DPTO", "DEPARTAMENTO", "AÑO", "SALARIO PROMEDIO", "EMPLEADOS", "MASA SALARIAL"]
    filas, anomalias = parse.parsear_empleados([
        head,
        ["140001", "L", 1, "D", 2025, "NA", "NA", "NA"],
        ["140002", "L", 1, "D", 2025, 1000, 10, f"#REF {MASA_CENTINELA}"],
    ])
    assert filas[0]["masa_salarial"] is None and filas[0]["empleados"] is None
    assert anomalias == [{"tipo": "valor_invalido", "codigo": "140002", "campo": "masa_salarial"}]
    assert str(MASA_CENTINELA) not in json.dumps(anomalias)


def test_parse_mes_y_quincena_en_texto():
    assert parse.mes_de("03 - marzo") == 3 and parse.mes_de("septiembre") == 9 and parse.mes_de("") is None
    assert parse.periodo_de("octubre 2023") == date(2023, 10, 1)
    assert parse.quincena_de("2°") == 2 and parse.quincena_de("x") is None
    assert parse.monto("-1.234,5") == (-1234.5, False) and parse.monto("NA") == (None, False)


def test_conciliar_mensual_marca_meses_y_localidades_que_no_cierran():
    planilla = {("A", date(2025, 1, 1)): 1000.0, ("B", date(2025, 1, 1)): 500.0, ("A", date(2025, 2, 1)): 10.0}
    transparencia = {("1", date(2025, 1, 1)): 1000.0, ("2", date(2025, 1, 1)): 450.0, (None, date(2025, 1, 1)): 50.0}
    meses = conciliacion.conciliar_mensual(planilla, transparencia, {"A": "1", "B": "2"})
    ene, feb = meses
    assert ene["planilla"] == 1500 and ene["transparencia"] == 1500 and ene["diferencia"] == pytest.approx(0)
    assert ene["localidades_con_diferencia"] == ["B"]
    assert feb["transparencia"] is None and feb["diferencia"] is None
    assert [m["periodo"] for m in conciliacion.resumen_para_log(meses)] == ["2025-01-01"]


# ── Sync ────────────────────────────────────────────────────────────────────────────

CODIGOS = [str(140001 + i) for i in range(5)]


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    for fuente in ("copa", "fofindes", "fodemep", "fommep", "empleados"):
        monkeypatch.setattr(settings, f"google_sheet_gob_{fuente}_id", fuente.upper())
    monkeypatch.setattr(settings, "gob_transferencias_sync_enabled", True)
    monkeypatch.setattr(gsync, "MIN_LOCALIDADES", 3)


def planillas(copa=None, otras: dict | None = None):
    head_fommep = ["ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "AÑO", "Cant_moviles", "Monto_moviles", "Cant_edificios_A",
                   "Monto_edificios_A", "Cant_edificios_B", "Monto_edificios_B", "Cant_edificios_C", "Monto_edificios_C",
                   "Cant_edificios_TOTAL", "Monto_edificios_TOTAL", "Monto_total"]
    head_emp = ["ID_LOC", "LOCALIDADES", "ID_DPTO", "DEPARTAMENTO", "AÑO", "SALARIO PROMEDIO", "EMPLEADOS", "MASA SALARIAL"]
    base = {
        ("COPA", "COPA"): copa if copa is not None else [HEAD_COPA] + [fila_copa(c, q) for c in CODIGOS for q in ("1°", "2°")],
        ("FOFINDES", "FOFINDES"): [HEAD_FOF] + [fila_fof(c) for c in CODIGOS],
        ("FODEMEP", "FODEMEP"): [HEAD_FODEMEP] + [[c, "L", "D", 0, 1, "M", 0.1, 100, 0, 100, ENE_2025 + 3, ENE_2025, 2025] for c in CODIGOS],
        ("FODEMEP", "ESTADO"): [["ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "ESTADO", "SALDO DE GESTION"]]
        + [[c, "L", "D", "NORMAL" if i else "SUSPENDIDO", -5] for i, c in enumerate(CODIGOS)],
        ("FOMMEP", "FROMMEP"): [head_fommep] + [[c, "L", "D", 2025, 1, 10, 1, 1, 0, 0, 0, 0, 1, 1, 15] for c in CODIGOS],
        ("EMPLEADOS", "Activos MyC"): [head_emp]
        + [[c, "L", 1, "D", 2025, 10, 5, MASA_CENTINELA] for c in CODIGOS]
        + [[CODIGOS[0], "L", 1, "D", 2024, 10, 5, 1.0]],
    }
    base.update(otras or {})
    leidas: list[tuple[str, str]] = []

    async def fake(spreadsheet_id, rango, render="FORMATTED_VALUE"):
        assert render == "UNFORMATTED_VALUE"
        pestana = rango.split("!")[0].strip("'")
        leidas.append((spreadsheet_id, pestana))
        valor = base[(spreadsheet_id, pestana)]
        if isinstance(valor, Exception):
            raise valor
        return valor

    return patch("app.gob_transferencias.sync.google_sheets.get_values", new=fake), leidas


async def _nomenclador(db: AsyncSession, codigos=CODIGOS[:4]) -> None:
    db.add_all([
        ExtGobLocalidad(codigo_indec=c, nombre_gob=f"LOC {c}", departamento_gob="D", tipo="MU", id_geo=f"g{c}")
        for c in codigos
    ])
    await db.commit()


async def _count(db, modelo) -> int:
    return (await db.execute(select(func.count()).select_from(modelo))).scalar_one()


async def test_sync_todas_las_fuentes(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    parche, leidas = planillas()
    with parche:
        r = await client.post("/internal/datos-externos/gobierno/transferencias/sync")
    assert r.status_code == 200, r.text
    logs = {x["fuente"]: x for x in r.json()}
    # Las planillas de fondos (Fase 3) no están configuradas acá: fallan solas, sin frenar al resto.
    fondos = {"fondo_permanente", "fondo_ambiental", "comunidades_regionales"}
    assert set(logs) == {"copa", "fofindes", "fodemep", "fommep", "empleados"} | fondos
    assert all(logs[f]["estado"] == "fallido" for f in fondos)
    logs = {f: x for f, x in logs.items() if f not in fondos}
    assert all(x["estado"] == "ok" for x in logs.values())
    # Solo las pestañas autorizadas (spec §0).
    assert sorted(p for _, p in leidas) == ["Activos MyC", "COPA", "ESTADO", "FODEMEP", "FOFINDES", "FROMMEP"]

    assert await _count(db_session, ExtGobCopa) == 10
    assert await _count(db_session, ExtGobFofindes) == 5
    assert await _count(db_session, ExtGobFodemep) == 5 and await _count(db_session, ExtGobFodemepEstado) == 5
    assert await _count(db_session, ExtGobFommep) == 5 and await _count(db_session, ExtGobEmpleados) == 6

    # El quinto código no está en el nomenclador: se guarda y se informa.
    assert logs["copa"]["filas_sin_match"] == 1
    assert {"tipo": "codigo_fuera_del_nomenclador", "codigo": CODIGOS[4]} in logs["copa"]["anomalias"]

    # La ficha restringida toma el último año con masa salarial.
    loc = (await db_session.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.codigo_indec == CODIGOS[0]))).scalar_one()
    await db_session.refresh(loc)
    assert float(loc.masa_salarial) == MASA_CENTINELA and loc.empleados == 5

    # La masa salarial nunca va a los logs.
    todos = (await db_session.execute(select(ExtGobSyncLog))).scalars().all()
    assert str(MASA_CENTINELA) not in json.dumps([x.anomalias for x in todos])


async def test_sync_reemplaza_y_el_freno_conserva_los_datos(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    parche, _ = planillas()
    with parche:
        await client.post("/internal/datos-externos/gobierno/transferencias/sync")

    # Segunda corrida con menos del 90 % de las filas: COPA no se toca; las demás sí corren.
    pocas = [HEAD_COPA] + [fila_copa(c) for c in CODIGOS]
    parche, _ = planillas(copa=pocas)
    with parche:
        r = await client.post("/internal/datos-externos/gobierno/transferencias/sync")
    logs = {x["fuente"]: x for x in r.json()}
    assert logs["copa"]["estado"] == "fallido" and "no se tocó ningún dato" in logs["copa"]["anomalias"][0]["detalle"]
    assert logs["fofindes"]["estado"] == "ok"
    assert await _count(db_session, ExtGobCopa) == 10

    # Con la cantidad normal se reemplaza completo (no se duplica).
    parche, _ = planillas()
    with parche:
        await client.post("/internal/datos-externos/gobierno/transferencias/sync", params={"fuente": "copa"})
    assert await _count(db_session, ExtGobCopa) == 10


async def test_sync_estructura_invalida_y_lectura_fallida(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    parche, _ = planillas(
        copa=[[h for h in HEAD_COPA if h != "Varios"]],
        otras={("FOFINDES", "FOFINDES"): RuntimeError("sheets caído")},
    )
    with parche:
        r = await client.post("/internal/datos-externos/gobierno/transferencias/sync", params={"fuente": "copa"})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "GOB_SYNC_FALLIDO"
    # El log de la falla sobrevive al rollback del 502.
    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "copa"))).scalar_one()
    assert log.estado == "fallido" and "VARIOS" in log.anomalias[0]["detalle"]

    with parche:
        r = await client.post("/internal/datos-externos/gobierno/transferencias/sync", params={"fuente": "fofindes"})
    assert r.status_code == 502 and "RuntimeError" in r.json()["detail"]["message"]


async def test_sync_deshabilitado_y_fuente_invalida(client: AsyncClient, monkeypatch):
    r = await client.post("/internal/datos-externos/gobierno/transferencias/sync", params={"fuente": "otra"})
    assert r.status_code == 422
    monkeypatch.setattr(settings, "gob_transferencias_sync_enabled", False)
    r = await client.post("/internal/datos-externos/gobierno/transferencias/sync")
    assert r.status_code == 503


async def test_sync_estado_y_conciliacion(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    db_session.add_all([
        ExtTransferencia(periodo=date(2025, 1, 1), tipo="municipio", id_geo=f"g{c}", nombre_pdf=c, departamento_pdf="D",
                         concepto="coparticipacion_ley_8663", monto=2000 if c != CODIGOS[1] else 1500)
        for c in CODIGOS[:4]
    ])
    await db_session.commit()
    parche, _ = planillas()
    with parche:
        await client.post("/internal/datos-externos/gobierno/transferencias/sync")

    r = await client.get("/internal/datos-externos/gobierno/transferencias/sync-estado")
    assert [x["fuente"] for x in r.json()][:5] == ["copa", "fofindes", "fodemep", "fommep", "empleados"]

    r = await client.get("/internal/datos-externos/gobierno/transferencias/conciliacion", params={"anio": 2025})
    ene = r.json()["transparencia"]["copa"][0]
    assert ene["periodo"] == "2025-01-01" and ene["planilla"] == 10000 and ene["transparencia"] == 7500
    assert ene["localidades_con_diferencia"] == [CODIGOS[1]] and ene["solo_planilla"] == 0
    assert "vista" in r.json()
