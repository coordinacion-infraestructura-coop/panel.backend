"""Tablero de Gobierno, Etapa 2: secciones desde las planillas de Gobierno
(spec-datos-externos-fase2-transferencias.md §5 y §9)."""
from datetime import date

from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.gob_transferencias.models import (
    ExtGobCopa,
    ExtGobEmpleados,
    ExtGobFodemep,
    ExtGobFodemepEstado,
    ExtGobFofindes,
    ExtGobFommep,
)
from app.gobierno.models import ExtGobLocalidad
from app.tablero.planillas import ultimo_mes_completo
from app.tablero.schemas import Pago
from app.transferencias.models import ExtTransferencia
from tests.conftest import CONSULTA_USER

URL = "/api/v1/datos-externos/tablero/transferencias"
MASA = 777123.0


def _copa(codigo, anio, mes, q, bruto, neto, caja=0.0, apross=0.0):
    return ExtGobCopa(
        codigo_indec=codigo, anio=anio, mes=mes, quincena=q, fecha_pago=date(anio, mes, 10 + 10 * (q - 1)),
        bruto=bruto, neto_a_transferir=neto, caja_jubilaciones=caja, apross=apross,
        descuentos={"Caja de Jubilaciones": caja, "APROSS": apross, "Varios": 0},
    )


async def _cargar(db: AsyncSession) -> None:
    db.add_all([
        ExtGobLocalidad(codigo_indec="A", nombre_gob="LOC A", departamento_gob="D1", tipo="MU", id_geo="1"),
        ExtGobLocalidad(codigo_indec="B", nombre_gob="LOC B", departamento_gob="D1", tipo="CO", id_geo="2"),
        ExtGobLocalidad(codigo_indec="C", nombre_gob="LOC C", departamento_gob="D2", tipo="MU", id_geo="3"),
        ExtGeoCenso(id="c-a", codigo_indec="A", categoria="MU", localidad_censo="LOC A", poblacion_2022=100),
        ExtGeoCenso(id="c-b", codigo_indec="B", categoria="CO", localidad_censo="LOC B", poblacion_2022=50),
        # 2026: enero completo, febrero solo la primera quincena.
        _copa("A", 2026, 1, 1, 1000, 800, caja=100, apross=50),
        _copa("A", 2026, 1, 2, 1000, 800, caja=100, apross=50),
        _copa("B", 2026, 1, 1, 400, 300, caja=40),
        _copa("B", 2026, 1, 2, 400, 300, caja=40),
        _copa("A", 2026, 2, 1, 1200, 900, caja=120),
        _copa("Z", 2026, 1, 1, 100, 100),  # código fuera del nomenclador
        # 2025
        _copa("A", 2025, 1, 1, 900, 700, caja=45),
        _copa("A", 2025, 1, 2, 900, 700, caja=45),
        _copa("A", 2025, 2, 1, 950, 700, caja=50),
        ExtGobFofindes(codigo_indec="A", anio=2026, mes=1, fecha_pago=date(2026, 2, 12), bruto=200, neto_a_transferir=190, descuentos={"Bomberos": 10}),
        ExtGobFofindes(codigo_indec="B", anio=2026, mes=1, fecha_pago=date(2026, 2, 12), bruto=100, neto_a_transferir=100, descuentos={}),
        ExtGobEmpleados(codigo_indec="A", anio=2025, empleados=10, salario_promedio=10, masa_salarial=MASA),
        ExtGobEmpleados(codigo_indec="A", anio=2026, empleados=10, salario_promedio=10, masa_salarial=1234.5),
        ExtGobEmpleados(codigo_indec="B", anio=2026, empleados=None, salario_promedio=None, masa_salarial=None),
        # Transparencia: mismo año, para ver que la planilla manda.
        ExtTransferencia(periodo=date(2026, 1, 1), tipo="municipio", id_geo="1", nombre_pdf="A", departamento_pdf="D1",
                         concepto="coparticipacion_ley_8663", monto=5),
    ])
    await db.commit()


def test_ultimo_mes_completo_pide_la_segunda_quincena():
    pagos = [Pago(anio=2026, mes=1, quincena=2, fecha_pago=None, bruto=1, neto=1),
             Pago(anio=2026, mes=2, quincena=1, fecha_pago=None, bruto=1, neto=1)]
    assert ultimo_mes_completo(pagos, 2026, por_quincena=True) == 1
    assert ultimo_mes_completo(pagos, 2026, por_quincena=False) == 2
    assert ultimo_mes_completo(pagos, 2025, por_quincena=True) is None


async def test_coparticipacion_desde_la_planilla(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    d = (await client.get(f"{URL}/coparticipacion", params={"anio": 2026})).json()
    assert d["fuente"] == "planilla" and d["fuente_anterior"] == "planilla"
    assert d["mensual"][:3] == [2900, 1200, None]
    assert d["mensual_neto"][:2] == [2300, 900]
    assert d["total_anio"] == 4100 and d["total_neto_anio"] == 3200
    # Mismo período del año anterior: enero y febrero de 2025.
    assert d["acumulado_anterior"] == 2750
    assert d["ultimo_pago"]["mes"] == 2 and d["ultimo_pago"]["quincena"] == 1
    assert d["ultimo_mes_completo"]["mes"] == 1 and d["ultimo_mes_completo"]["bruto"] == 2900
    assert len(d["pagos"]) == 3 and d["localidades"] == 3
    assert d["descuentos"][0] == {"concepto": "Caja de Jubilaciones", "etiqueta": "Caja de Jubilaciones", "monto": 400}

    ret = d["retenciones"]
    assert ret["mes_referencia"] == 1
    assert [r["anio"] for r in ret["mismo_mes"]] == [2025, 2026]
    assert ret["mismo_mes"][1]["caja"] == pytest.approx(280 / 2900)
    assert ret["mensual"][1]["caja"][1] == pytest.approx(0.1)
    # Acumulado de 2026 a febrero: (100+100+40+40+120) / (2900+1200)
    assert ret["mensual"][1]["acumulado_caja"][1] == pytest.approx(400 / 4100)

    # % a sueldos: masa 2026 de A (B no tiene) sobre COPA + FOFINDES de enero de A.
    s = d["pct_sueldos"]
    assert s["anio_masa"] == 2026 and s["mes_referencia"] == "2026-01-01"
    assert s["bruto"] == pytest.approx(1234.5 / (2000 + 200)) and s["neto"] == pytest.approx(1234.5 / (1600 + 190))
    assert s["localidades_con_dato"] == 1 and s["localidades"] == 3 and s["incluye_fofindes"]
    assert str(MASA) not in str(d) and "1234.5" not in str(d)


async def test_coparticipacion_filtrada_y_caida_a_transparencia(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    d = (await client.get(f"{URL}/coparticipacion", params={"anio": 2026, "codigo_indec": ["B"]})).json()
    assert d["mensual"][0] == 800 and d["pct_sueldos"]["localidades_con_dato"] == 0
    assert d["pct_sueldos"]["bruto"] is None and d["pct_sueldos"]["anio_masa"] is None

    # 2024 no está en la planilla: cae a Transparencia y lo dice.
    d = (await client.get(f"{URL}/coparticipacion", params={"anio": 2024})).json()
    assert d["fuente"] == "transparencia" and d["pct_sueldos"] is None and d["pagos"] == []


async def test_fofindes_desde_la_planilla(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    d = (await client.get(f"{URL}/fofindes", params={"anio": 2026})).json()
    assert d["fuente"] == "planilla" and d["mensual"][0] == 300 and d["total_neto_anio"] == 290
    assert d["ultimo_mes_completo"]["mes"] == 1 and d["retenciones"] is None and d["pct_sueldos"] is None
    assert d["descuentos"] == [{"concepto": "Bomberos", "etiqueta": "Bomberos", "monto": 10}]


async def test_fodemeep(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    db_session.add_all([
        ExtGobFodemep(codigo_indec="A", periodo=date(2025, 12, 1), presupuestado=100, acumulado=0, neto_a_transferir=100),
        ExtGobFodemep(codigo_indec="A", periodo=date(2026, 1, 1), presupuestado=100, acumulado=0, neto_a_transferir=100),
        ExtGobFodemep(codigo_indec="B", periodo=date(2026, 1, 1), presupuestado=80, acumulado=80, neto_a_transferir=0),
        ExtGobFodemep(codigo_indec="B", periodo=date(2026, 2, 1), presupuestado=80, acumulado=0, neto_a_transferir=160),
        ExtGobFodemepEstado(codigo_indec="A", estado="NORMAL", saldo_gestion=0),
        ExtGobFodemepEstado(codigo_indec="B", estado="SUSPENDIDO", saldo_gestion=-3),
    ])
    await db_session.commit()
    d = (await client.get(f"{URL}/fodemeep", params={"anio": 2026})).json()
    k = d["kpis"]
    assert k["localidades"] == 2 and k["presupuestado_gestion"] == 360 and k["transferido_gestion"] == 360
    assert k["ultimo_periodo"] == "2026-02-01" and k["transferido_ultimo"] == 160
    assert d["mensual_transferido"][:3] == [100, 160, None] and d["mensual_retenido"][:2] == [80, 0]
    assert [(f["codigo_indec"], f["total"], f["estado"]) for f in d["por_localidad"]] == [("A", 100, "NORMAL"), ("B", 160, "SUSPENDIDO")]
    assert {e["estado"]: e["cantidad"] for e in d["estados"]} == {"NORMAL": 1, "SUSPENDIDO": 1, "SIN DATO": 1}


async def test_fommep_usa_su_propio_anio(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    db_session.add_all([
        ExtGobFommep(codigo_indec="A", anio=2025, cant_moviles=2, monto_moviles=20, cant_edificios_a=1, monto_edificios_a=5,
                     cant_edificios_b=0, monto_edificios_b=0, cant_edificios_c=0, monto_edificios_c=0,
                     cant_edificios_total=1, monto_edificios_total=5, monto_total=40),
        ExtGobFommep(codigo_indec="B", anio=2024, cant_moviles=1, monto_moviles=10, cant_edificios_total=0,
                     monto_edificios_total=0, monto_total=10),
    ])
    await db_session.commit()
    d = (await client.get(f"{URL}/fommep", params={"anio": 2026})).json()
    assert d["anios"] == [2025, 2024]
    k = d["por_anio"][0]["kpis"]
    assert d["por_anio"][0]["anio"] == 2025
    assert k["localidades"] == 1 and k["monto_total"] == 40 and k["moviles"] == {"cantidad": 2, "monto": 20}
    assert k["otros"] == 15
    assert d["gestion"]["monto_total"] == 50 and d["gestion"]["localidades"] == 2
    assert [(f["codigo_indec"], f["anio"]) for f in d["por_localidad"]] == [("A", 2025), ("B", 2024)]


async def test_resumen(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    d = (await client.get(f"{URL}/resumen", params={"anio": 2026})).json()
    assert d["periodo_hasta"] == "2026-02-01"
    # Sin filtro el total suma también el código fuera del nomenclador.
    assert d["total"]["copa"] == 3200 and d["total"]["fofindes"] == 290 and d["total"]["total"] == 3490
    a = next(f for f in d["por_localidad"] if f["clave"] == "A")
    assert a["copa"] == 2500 and a["fofindes"] == 190 and a["por_habitante"] == pytest.approx(26.9)
    d1 = next(f for f in d["por_departamento"] if f["clave"] == "D1")
    assert d1["total"] == 2500 + 600 + 290 and d1["poblacion"] == 150


async def test_secciones_nuevas_solo_admin_y_autoridad(client: AsyncClient, as_user):
    as_user(CONSULTA_USER)
    for s in ("fodemeep", "fommep", "resumen"):
        assert (await client.get(f"{URL}/{s}", params={"anio": 2026})).status_code == 403
