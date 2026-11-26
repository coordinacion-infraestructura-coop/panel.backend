"""Fase 3b: planilla "0. Fondo Federal" (spec-datos-externos-fase3b-fondo-federal.md §7)."""
from datetime import date
from unittest.mock import patch

from httpx import AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_fondos import parse
from app.gob_fondos.models import ExtGobFfedCopa, ExtGobFfedEtapa, ExtGobFondoValor
from app.gob_transferencias import sync as gsync
from app.gobierno.models import ExtGobLocalidad, ExtGobSyncLog
from app.tablero import fondo_federal
from tests.conftest import AUTORIDAD_USER, CONSULTA_USER

SYNC = "/internal/datos-externos/gobierno/transferencias/sync"
URL = "/api/v1/datos-externos/tablero/transferencias/fondo-federal"
INTENDENTE = "PERSONA CENTINELA"
PARTIDO = "PARTIDO CENTINELA"
OBS = "Falta la DDJJ. Notificado a muni@ejemplo.com"

ENCABEZADO = [
    "ETAPA", "PARTE", "RESO", "FECHA RESO", "ID_LOC", "LOCALIDAD", "ID_DPTO", "DEPARTAMENTO", "TIPO",
    "CATEGORÍA POBLACIÓN", "MONTO ETAPA", "DISPONIBLE ETAPA", "ESTADO", "INTENDENTE", "PARTIDO",
    "ORDENANZA/RESOLUCIÓN", "FECHA INGRESO", "STICKER PEDIDO", "OTORGADO", "CUOTA", "PLAZO (MESES)",
    "FECHA DE ENTREGA", "INICIO DESCUENTO COPA", "RENDICIÓN", "DESTINO", "DESTINO DEL PRÉSTAMO", "SALDO",
    "DEVUELTO", "CUOTAS DEVUELTA", "AMORTIZACIÓN", "OBSERVACIONES", "FECHA DE AVISO", "STICKER RENDICION", "TRÁMITE",
]
# Serial de Sheets: 45776 = 2025-04-29, 45915 = 2025-09-15, 46009 = 2025-12-18, 46160 = 2026-05-18.


def _fila(etapa, codigo, monto, disponible, estado, otorgado=None, entrega=None, saldo=None, devuelto=None,
          rendicion="", obs="", aviso=None, amort=None):
    pagada = otorgado is not None
    return [
        etapa, 0, "2/25", 45776, codigo, "NOMBRE", 14001, "DEPTO", "MU", 7, monto, disponible, estado,
        INTENDENTE, PARTIDO, "1/2025" if pagada else "", 45800 if pagada else "", 1143217 if pagada else "",
        otorgado if pagada else "", (otorgado / 60) if pagada else "", 60 if pagada else "", entrega or "",
        entrega or "", rendicion, "VIAL URBANA" if pagada else "", "Bacheo" if pagada else "",
        saldo if saldo is not None else "", devuelto if devuelto is not None else "", 3 if pagada else "-",
        amort if amort is not None else ("NO" if pagada else ""), obs, aviso, "", "",
    ]


ETAPAS = [
    ["", "", "", "", "DATOS DE LOS MUNICIPIOS Y COMUNAS"],  # fila 1: títulos de grupo
    ENCABEZADO,
    # 140001: cobró 1 y 2 (rendidas), la 3 sin rendir; la 4 lista para pagar.
    _fila(1, 140001, 100, 0, "PAGADO", 100, 45915, 80, 20, rendicion="0563854"),
    _fila(2, 140001, 100, 0, "PAGADO", 100, 46009, 90, 10, rendicion=189278),
    _fila(3, 140001, 100, 0, "PAGADO SIN RENDIR", 100, 46160, 100, 0, obs=OBS, aviso="22/10/2025 por CIDI y x@y.com"),
    _fila(4, 140001, 100, 100, "LISTO PARA PAGAR"),
    # 140002: cobró todas; una extra pagada en dos partes.
    _fila(1, 140002, 50, 0, "PAGADO", 50, 45915, 40, 10, rendicion=1),
    _fila(2, 140002, 50, 0, "PAGADO", 50, 46009, 45, 5, rendicion=2),
    _fila(3, 140002, 50, 0, "PAGADO", 50, 46009, 48, 2, rendicion=3),
    _fila(4, 140002, 50, 0, "PAGADO", 50, 46160, 50, 0, rendicion=4),
    _fila("EXTRA 2 (PARCIAL)", 140002, 300, 200, "PAGADO", 100, 46160, 100, 0, rendicion=5),
    _fila("EXTRA 2 (SALDO)", 140002, 300, 200, "DISPONIBLE"),
    # 140003: no cobró nada; tiene dos disponibles y un pedido observado.
    _fila(1, 140003, 20, 20, "PEDIDO OBSERVADO", obs="Supera el índice de endeudamiento", aviso=46009),
    _fila(2, 140003, 20, 20, "DISPONIBLE"),
    _fila(3, 140003, 20, 20, "DISPONIBLE"),
    _fila(4, 140003, 20, 20, "DISPONIBLE", amort="#REF!"),
    # 140004: no adherida.
    _fila(1, 140004, 10, 10, "NO ADHERIDO"),
    # Relleno de la grilla.
    *([[None] * 28 + ["-"]] * 5),
]

RESUMEN = [
    [],
    ["", "DATOS RESUMEN DEL FONDO PERMANENTE", "", "", "", "", "", "PERFIL DE VENCIMIENTOS"],
    ["", "SALDO EN CUENTA FP", "", "", 9000.5],
    ["", "ETAPAS SIN ENTREGAR (DISPONIBLE)", "", "", 460],
    ["", "ETAPAS EN PROCESO", "", "", 120],
    ["", "DÉFICIT/SUPERAVIT", "", "", -50],
    [],
    ["", "AMORTIZACIONES RESTANTES", "", "", 553],
    ["", "TIEMPO MEDIO DE LAS AMORTIZACIONES (MESES)", "", "", 25.1],
    [],
    ["", "DATOS RESUMEN DEL FONDO PERMANENTE POR LOCALIDAD"],
    ["", "SALDO EN CUENTA FP", "", "", 1],  # bloque por localidad: no se lee
]

COPA = [
    ["ID_COPA", "ID_LOC", "LOCALIDAD", "AÑO", "APORTE FONDO PERMANENTE", "DEVOLUCIÓN FONDO PERMANENTE",
     "Actualizado hasta la  Copa de AGOSTO /2026"],
    [1, 140001, "NOMBRE", 2026, 30, 12],
    [2, 140002, "NOMBRE", 2026, 20, 8],
    [3, 140003, "NOMBRE", 2026, 10, 0],
    [4, 140001, "NOMBRE", 2025, 25, 5],
    [5, 140002, "NOMBRE", 2025, 15, 0],
    [6, 140003, "NOMBRE", 2025, 5, 0],
]

PLANILLAS = {"1. Etapas habilitadas": ETAPAS, "0. Resumen": RESUMEN, "6. Copa": COPA}


# ── Parseo puro ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,esperado", [
    (1, ("1", 1, False)), ("4", ("4", 4, False)), ("EXTRA", ("EXTRA", None, True)),
    ("EXTRA 2 (SALDO)", ("EXTRA 2 (SALDO)", 2, True)), ("Extra 1", ("Extra 1", 1, True)),
    ("EXTRA 3 PARCIAL 1", ("EXTRA 3 PARCIAL 1", 3, True)), ("R", ("R", None, False)), ("", (None, None, False)),
])
def test_etapa_ffed(raw, esperado):
    assert parse.etapa_ffed(raw) == esperado


def test_parsear_etapas():
    filas, anomalias = parse.parsear_ffed_etapas(ETAPAS[1:])
    assert len(filas) == 15
    primera = filas[0]
    assert primera["fila"] == 3  # fila real de la planilla
    assert primera["fecha_entrega"] == date(2025, 9, 15) and primera["fecha_resolucion"] == date(2025, 4, 29)
    assert primera["sticker_rendicion"] == "0563854" and filas[1]["sticker_rendicion"] == "189278"
    assert primera["amortizada"] is False and primera["cuotas_devueltas"] == 3
    sin_rendir = filas[2]
    assert sin_rendir["fecha_aviso"] == date(2025, 10, 22) and sin_rendir["aviso_texto"].startswith("22/10/2025")
    assert filas[10]["fecha_aviso"] == date(2025, 12, 18) and filas[10]["aviso_texto"] is None
    assert {(f["etapa_texto"], f["etapa_numero"], f["es_extra"]) for f in filas if f["es_extra"]} == {
        ("EXTRA 2 (PARCIAL)", 2, True), ("EXTRA 2 (SALDO)", 2, True),
    }
    tipos = {a["tipo"] for a in anomalias}
    assert {"valor_invalido", "filas_de_relleno"} <= tipos
    assert {"tipo": "filas_de_relleno", "cantidad": 5} in anomalias
    # Las columnas de personas no llegan a ninguna fila (el parser ni las mira).
    assert not any(INTENDENTE in str(v) or PARTIDO in str(v) for f in filas for v in f.values())


def test_parsear_resumen_y_copa():
    valores, anom = parse.parsear_ffed_resumen(RESUMEN)
    assert {v["concepto"]: v["monto"] for v in valores} == {
        "saldo_cuenta": 9000.5, "disponible": 460, "en_proceso": 120, "deficit_superavit": -50,
        "amortizaciones_restantes": 553, "tiempo_medio_amortizacion": 25.1,
    }
    assert anom == []
    assert parse.parsear_ffed_resumen([["", "OTRA COSA", "", "", 1]])[1][0]["tipo"] == "valor_de_control_faltante"
    copa, anom = parse.parsear_ffed_copa(COPA)
    assert len(copa) == 6 and anom == []
    assert parse.parsear_ffed_copa_actualizada(COPA)[0] == [
        {"fondo": parse.FONDO_FEDERAL_COPA, "concepto": "actualizado_hasta", "anio": 2026, "monto": 8}
    ]


# ── Sync ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_gob_fondo_federal_id", "FF")
    monkeypatch.setattr(settings, "gob_transferencias_sync_enabled", True)
    monkeypatch.setattr(gsync, "MIN_LOCALIDADES", 3)


def _col(letras: str) -> int:
    n = 0
    for c in letras:
        n = n * 26 + ord(c) - 64
    return n - 1


def _parches(planillas: dict):
    pedidos: list[str] = []

    def partes(rango: str) -> tuple[str, str]:
        pestana, celdas = rango.split("!")
        return pestana.strip("'"), celdas

    async def get_values(sheet_id, rango, render="FORMATTED_VALUE"):
        assert sheet_id == "FF"
        pedidos.append(rango)
        pestana, celdas = partes(rango)
        valores = planillas[pestana]
        if ":" in celdas and celdas.split(":")[0].isdigit():  # una fila: `2:2`
            n = int(celdas.split(":")[0])
            return valores[n - 1 : n]
        return valores

    async def batch_get(sheet_id, rangos, render="FORMATTED_VALUE"):
        out = []
        for rango in rangos:
            pedidos.append(rango)
            pestana, celdas = partes(rango)
            desde, hasta = (_col(x.rstrip("0123456789")) for x in celdas.split(":"))
            out.append([fila[desde : hasta + 1] for fila in planillas[pestana]])
        return out

    return (
        patch("app.gob_transferencias.sync.google_sheets.get_values", new=get_values),
        patch("app.gob_transferencias.sync.google_sheets.batch_get_values", new=batch_get),
        pedidos,
    )


async def _nomenclador(db: AsyncSession) -> None:
    db.add_all([
        ExtGobLocalidad(codigo_indec=c, nombre_gob=f"L{c[-1]}", departamento_gob="D1" if c < "140003" else "D2", tipo="MU", id_geo=f"g{c}")
        for c in ("140001", "140002", "140003", "140004")
    ])
    await db.commit()


async def _sync(client: AsyncClient, planillas: dict | None = None):
    p1, p2, pedidos = _parches({**PLANILLAS, **(planillas or {})})
    with p1, p2:
        r = await client.post(SYNC, params={"fuente": "fondo_federal"})
    return r, pedidos


async def _count(db, modelo, *where) -> int:
    return (await db.execute(select(func.count()).select_from(modelo).where(*where))).scalar_one()


async def test_sync_fondo_federal(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    r, pedidos = await _sync(client)
    assert r.status_code == 200, r.text

    # Intendente y partido nunca se piden: los rangos de la pestaña de etapas los saltean.
    etapas = [p for p in pedidos if p.startswith("'1. Etapas habilitadas'")]
    assert "'1. Etapas habilitadas'!2:2" in etapas
    assert "'1. Etapas habilitadas'!A1:M" in etapas and "'1. Etapas habilitadas'!P1:AH" in etapas
    assert not any(INTENDENTE in str(v) or PARTIDO in str(v) for e in (await db_session.execute(select(ExtGobFfedEtapa))).scalars() for v in vars(e).values())

    assert await _count(db_session, ExtGobFfedEtapa) == 15
    assert await _count(db_session, ExtGobFfedCopa) == 6
    assert await _count(db_session, ExtGobFondoValor, ExtGobFondoValor.fondo == parse.FONDO_FEDERAL) == 6
    assert await _count(db_session, ExtGobFondoValor, ExtGobFondoValor.fondo == parse.FONDO_FEDERAL_COPA) == 1

    log = (await db_session.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == "fondo_federal"))).scalar_one()
    assert log.estado == "ok"
    # Disponible del resumen (460) = DISPONIBLE + REMANENTE de las filas (200 + 20 × 3 = 260): no cierra.
    control = next(a for a in log.anomalias if a["tipo"] == "control_disponible_vs_resumen")
    assert control["diferencia"] == 200
    # Ni el log lleva observaciones ni correos.
    assert "ejemplo.com" not in str(log.anomalias)


async def test_sync_fondo_federal_frena_si_la_planilla_viene_corta(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    corta = ETAPAS[:6]  # una sola localidad
    r, _ = await _sync(client, {"1. Etapas habilitadas": corta})
    assert r.status_code == 502
    assert await _count(db_session, ExtGobFfedEtapa) == 15  # quedó lo anterior


# ── Tablero ───────────────────────────────────────────────────────────────────────


async def test_tablero_fondo_federal(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    r = await client.get(URL, params={"anio": 2026})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["concepto"] == "fondo-federal" and d["ver_observaciones"] is True
    assert d["resumen"]["saldo_cuenta"] == 9000.5 and d["resumen"]["tiempo_medio_amortizacion"] == 25.1
    assert d["ultima_etapa_habilitada"] == 4
    assert d["localidades_adheridas"] == 3  # 140004 no adhirió
    assert d["recibieron_ultima"] == 1 and d["recibieron_anteultima"] == 2
    assert d["deben_rendicion"] == 1 and d["con_pendientes"] == 3
    assert d["otorgado"] == 300 + 200 + 100
    assert [e["estado"] for e in d["estados"]] == ["PAGADO", "PAGADO SIN RENDIR", "LISTO PARA PAGAR", "PEDIDO OBSERVADO", "DISPONIBLE", "NO ADHERIDO"]
    assert d["anios"] == [2026, 2025]
    a2026 = d["por_anio"][0]
    assert a2026["otorgado"] == 100 + 50 + 100 and a2026["mensual"][4] == 250
    assert d["copa"] == [{"anio": 2026, "aporte": 60, "devolucion": 20}, {"anio": 2025, "aporte": 45, "devolucion": 5}]
    assert d["copa_actualizada_hasta"] == "2026-08"

    loc = {x["codigo_indec"]: x for x in d["localidades"]}
    l1 = loc["140001"]
    assert l1["ultima_etapa"] == "4" and l1["estado_ultima_etapa"] == "LISTO PARA PAGAR"
    assert l1["ultima_etapa_cobrada"] == "3" and l1["etapas_cobradas"] == ["1", "2", "3"]
    assert l1["pendientes"] == [{"etapa": "4", "estado": "LISTO PARA PAGAR", "monto": 100}]
    assert l1["sin_rendir"] == ["3"] and l1["debe_rendicion"] is True
    assert l1["saldo"] == 270 and l1["devuelto"] == 30 and l1["observaciones"] == 1
    e3 = next(e for e in l1["etapas"] if e["etapa"] == "3")
    assert e3["tiene_observacion"] and e3["observaciones"] == OBS and e3["aviso_texto"].startswith("22/10/2025")

    l2 = loc["140002"]
    assert l2["ultima_etapa_cobrada"] == "4" and l2["debe_rendicion"] is False
    assert [e["etapa"] for e in l2["etapas"]][-2:] == ["EXTRA 2 (PARCIAL)", "EXTRA 2 (SALDO)"]
    assert l2["pendientes"] == [{"etapa": "EXTRA 2 (SALDO)", "estado": "DISPONIBLE", "monto": 200}]

    l3 = loc["140003"]
    assert l3["ultima_etapa_cobrada"] is None and len(l3["pendientes"]) == 4
    assert loc["140004"]["adherida"] is False


async def test_tablero_fondo_federal_con_filtro(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    d = (await client.get(URL, params={"anio": 2026, "codigo_indec": ["140003"]})).json()
    # El resumen es del fondo entero; la última etapa habilitada es la de la provincia.
    assert d["resumen"] is None and d["ultima_etapa_habilitada"] == 4
    assert [x["codigo_indec"] for x in d["localidades"]] == ["140003"]
    assert d["recibieron_ultima"] == 0 and d["otorgado"] == 0
    assert d["copa"] == [{"anio": 2026, "aporte": 10, "devolucion": 0}, {"anio": 2025, "aporte": 5, "devolucion": 0}]


async def test_observaciones_solo_admin_y_autoridad(client: AsyncClient, db_session: AsyncSession, as_user):
    await _nomenclador(db_session)
    await _sync(client)
    as_user(AUTORIDAD_USER)
    d = (await client.get(URL, params={"anio": 2026})).json()
    assert d["ver_observaciones"] is True
    # Cualquier otro rol (hoy el router ya lo frena con 403) ve que hay observación, no el texto.
    r = await fondo_federal.get_fondo_federal(db_session, None, "Operador")
    assert r.ver_observaciones is False
    etapas = [e for loc in r.localidades for e in loc.etapas]
    assert any(e.tiene_observacion for e in etapas)
    assert all(e.observaciones is None and e.aviso_texto is None for e in etapas)
    assert "ejemplo.com" not in r.model_dump_json() and "x@y.com" not in r.model_dump_json()


async def test_fondo_federal_403_para_otros_roles(client: AsyncClient, as_user):
    as_user(CONSULTA_USER)
    assert (await client.get(URL, params={"anio": 2026})).status_code == 403
