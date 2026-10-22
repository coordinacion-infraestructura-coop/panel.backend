"""Fase 6: Político — padrón de intendentes y elecciones (spec-datos-externos-fase6-politico.md §8).

Datos sintéticos: ningún nombre, partido ni teléfono real."""
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_politico import parse
from app.gob_politico.models import (
    ExtGobCircuitoLocalidad,
    ExtGobEleccionCircuito,
    ExtGobEleccionCopia,
    ExtGobEleccionMunicipal,
    ExtGobIntendente,
    ExtPrivPadronPolitico,
)
from app.gob_transferencias import sync as gsync
from app.gobierno.models import ExtGobLocalidad, ExtGobSyncLog
from tests.conftest import CONSULTA_USER
from tests.test_gob_fondos import gsync_col

SYNC = "/internal/datos-externos/gobierno/transferencias/sync"
URL = "/api/v1/datos-externos/tablero/politico"
CENTINELA = "PERSONA CENTINELA"
TELEFONO = 3510000000

INTENDENTES = [
    ["ID_LOC", "Localidades", "DEPARTAMENTO", "INTENDENTE", "REELECTO", "PARTIDO", "CONTINUIDAD", "CELULAR", "FOTO"],
    [140001, "L1", "D1", "INT A", "SI", "PARTIDO X", "NO", TELEFONO, "https://drive.google.com/x"],
    [140002, "L2", "D1", "INT B", "NO", "PARTIDO Y", "SI", "351 000-0001", ""],
    [140003, "L3", "D2", "INT C", "QUIZAS", "PARTIDO X", "SI", "", "no es enlace"],
    ["428", "COMUNIDAD REGIONAL", "D1", "", "", "", "", "", ""],
]
C25 = [
    ["circuito_id", "circuito_nombre", "seccion_nombre", "padrón", "mesas", "nulos", "blancos", "comando", "impugnados",
     "totalVotos", "afirmativos", "validos", "ALIANZA LA LIBERTAD AVANZA", "ALIANZA PROVINCIAS UNIDAS", "DEFENDAMOS CÓRDOBA",
     "ALIANZA FUERZA PATRIA"],
    [1, "C1", "D1", 100, 1, 0, 0, 0, 0, 80, 80, 80, 40, 30, 5, 5],
    [2, "C2", "D1", 100, 1, 0, 0, 0, 0, 60, 60, 60, 10, 30, 10, 10],
    ["3A", "C3", "D1", 50, 1, 0, 0, 0, 0, 40, 40, 40, 5, 10, 5, 20],
    [4, "C4", "D2", 50, 1, 0, 0, 0, 0, 20, 20, 20, 10, 5, 3, 2],
    [5, "C5", "D2", 10, 1, 0, 0, 0, 0, 10, 10, 10, 5, 5, 0, 0],  # sin localidad
]
C23 = [
    ["circuito_id", "circuito_nombre", "seccion_nombre", "nulos", "blancos", "comando", "impugnados", "totalVotos", "afirmativos",
     "validos", "POSITIVO_HACEMOS POR NUESTRO PAIS", "POSITIVO_JUNTOS POR EL CAMBIO", "POSITIVO_LA LIBERTAD AVANZA", "RECURRIDO", "OTROS"],
    [1, "C1", "D1", 0, 0, 0, 0, 50, 50, 50, 20, 10, 10, 0, 10],
    [2, "C2", "D1", 0, 0, 0, 0, 50, 50, 50, 30, 10, 5, 0, 5],
    ["3A", "C3", "D1", 0, 0, 0, 0, 40, 40, 40, 10, 20, 5, 0, 5],
    [4, "C4", "D2", 0, 0, 0, 0, 20, 20, 20, 5, 5, 8, 0, 2],
]
C21 = [
    ["circuito_id", "circuito_nombre", "seccion_nombre", "NULOS", "BLANCOS", "COMANDO", "IMPUGNADOS", "totalVotos", "afirmativos",
     "validos", "POSITIVO_HACEMOS POR CÓRDOBA", "POSITIVO_JUNTOS POR EL CAMBIO", "POSITIVO_LA LIBERTAD AVANZA", "RECURRIDOS", "OTROS"],
    [1, "C1", "D1", 0, 0, 0, 0, 10, 10, 10, 5, 4, 1, 0, 0],
]
RVC = [
    ["", "", "", "", "", "", "2025"],
    ["LOCALIDAD", "circuito_id", "circuito_nombre", "seccion_nombre", "Intendente", "Partido", "padron_2025"],
    ["L1", 1, "C1", "D1", CENTINELA, CENTINELA, 100],
    ["L1", 2, "C2", "D1", CENTINELA, CENTINELA, 100],
    ["L2", "3a", "C3", "D1", CENTINELA, CENTINELA, 50],
    ["L3", 4, "C4", "D2", CENTINELA, CENTINELA, 50],
    ["", 5, "C5", "D2", CENTINELA, CENTINELA, 10],  # paraje sin gobierno local
]
MUNICIPALES = [
    ["Periodo", "Departamento", "ID_LOC", "Nombre_Localidad", "Tipo_Gob", "Fecha_elec", "Particip elect", "Total Votos AFIRMATIVOS",
     "Total PADRON", "Partido_Político_Ganador", "Partido_Politico_Ganador_Norm", "Votos_Posit_Ganador", "%_Ganador", "Sexo",
     "Nombre_Gobernante", "Partido_Politico_2do", "Partido_Politico_2do_norm", "Votos_Posit_2do", "%_Segundo", "Nombre_Segundo",
     "Votos_Otras_Fuerzas", "%_Otras_                Fuerzas"],
    ["2023-2027", "D1", 140001, "L1", "Municipio", 45100, 0.8, 100, 125, "LISTA X", "X", 60, 0.6, "F", "GOB A", "LISTA Y", "Y", 40, 0.4, "SEG A", 0, 0],
    ["2023-2027", "D1", 140002, "L2", "Comuna", 45100, "s/d", "s/d", 50, "LISTA Y", "Y", "s/d", "s/d", "M", "GOB B", "-", "-", "s/d", "s/d", "-", "s/d", "s/d"],
]
_G25 = ["", "", "", "", "", "", "DIPUTADOS 2025"]
CALVO = [
    _G25,
    ["LOCALIDAD", "DEPARTAMENTO", "INTENDENTE", "PARTIDO", "HABITANTES", "PADRÓN", "LLA", "PU", "DC", "OTROS", "GANADOR", "SEGUNDO",
     "DIFERENCIA GANADOR vs SEGUNDO", "DIFERENCIA LLA vs PU", "CAND A (HxC)", "CAND B \n(JxC)", "CAND C (LLA)", "CAND D (FdT)", "OTROS (G-23)",
     "HxC", "JxC", "LLA 23", "OTROS (D-23)", "HxC 21", "JxC 21", "LLA 21", "OTROS (D-21)"],
    # L1 2025: LLA 50/140, PU 60/140, DC 15/140, FP 15/140 -> ganador PU, segundo LLA. La planilla pone mal el segundo.
    ["L1", "D1", CENTINELA, CENTINELA, 999, 200, 50 / 140, 60 / 140, 15 / 140, 15 / 140, "PU", "DC", 10 / 140, 10 / 140,
     0.5, 0.2, 0.1, 0.1, 0.1, 0.5, 0.2, 0.15, 0.15, 0.5, 0.4, 0.1, 0.0],
    # L2: % de LLA mal pegado; gobernador no suma 100 %.
    ["L2", "D1", CENTINELA, CENTINELA, 999, 50, 0.9, 0.25, 0.125, 0.5, "FP", "PU", 0.25, 0.125,
     0.2, 0.4, 0.1, 0.1, 0.1, 0.25, 0.5, 0.125, 0.125, None, None, None, None],
]
GANADORES = [
    ["", "", "", "", ""],
    ["ORDEN", "LOCALIDAD", "seccion_nombre", "Intendente", "ALIADO", "Partido", "2025", "2023", "2021"],
    [1, "L1", "D1", CENTINELA, "PURO", CENTINELA, "PU", "HxC", "HxC"],
    [2, "L3", "D2", CENTINELA, "2.OPOSICIÓN", CENTINELA, "LLA", "LLA", "-"],
]
RESUMEN_VOTOS = [
    ["", "", "", "", "", "2025", "", "", "", "", "2023", "", "", "", "", "2021"],
    ["LOCALIDAD", "DEPARTAMENTO", "Intendente", "Partido", "PADRÓN", "Afirmativos", "LLA", "PU", "DC", "OTROS",
     "Afirmativos", "HxC", "JxC", "LLA", "OTROS", "Afirmativos", "HxC", "JxC", "LLA", "OTROS"],
    ["L1", "D1", CENTINELA, CENTINELA, 200, 140, 50, 60, 15, 15, 100, 50, 20, 15, 15, 10, 5, 4, 1, 0],
    ["L3", "D2", CENTINELA, CENTINELA, 50, 20, 10, 5, 3, 3, 20, 5, 5, 8, 2, 0, 0, 0, 0, 0],  # OTROS 2025 mal: es 2
]
PLANILLAS = {
    ("RE", "Intendentes"): INTENDENTES,
    ("EL", "2025"): C25,
    ("EL", "2023"): C23,
    ("EL", "2021"): C21,
    ("EL", "RESUMEN_VOTOS_CIRCUITOS"): RVC,
    ("EL", "Municipales - 2023"): MUNICIPALES,
    ("EL", "RESULTADOS CALVO"): CALVO,
    ("EL", "GANADORES"): GANADORES,
    ("EL", "RESUMEN_VOTOS"): RESUMEN_VOTOS,
}


# ── Parseo ────────────────────────────────────────────────────────────────────────


def test_parsear_intendentes():
    filas, anom = parse.parsear_intendentes(INTENDENTES)
    assert [f["codigo_indec"] for f in filas] == ["140001", "140002", "140003"]  # sin la comunidad regional
    assert filas[0]["reelecto"] is True and filas[0]["continuidad"] is False
    assert filas[0]["celular"] == str(TELEFONO) and filas[1]["celular"] == "3510000001"
    assert filas[2]["reelecto"] is None and filas[2]["foto_url"] is None
    assert {a["tipo"]: a["cantidad"] for a in anom} == {"si_no_invalido": 1, "sin_celular": 1}
    assert str(TELEFONO) not in str(anom)


def test_parsear_circuitos_fuerzas_variables():
    filas, _ = parse.parsear_circuitos("diputados_2023")(C23)
    assert filas[0]["votos"] == {"HACEMOS POR NUESTRO PAIS": 20, "JUNTOS POR EL CAMBIO": 10, "LA LIBERTAD AVANZA": 10, "OTROS": 10}
    assert filas[0]["padron"] is None and filas[0]["recurridos"] == 0
    filas, _ = parse.parsear_circuitos("diputados_2025")(C25)
    assert filas[2]["circuito_id"] == "3A" and filas[0]["padron"] == 100
    assert "DEFENDAMOS CORDOBA" in filas[0]["votos"]


def test_parsear_municipales_y_copias():
    filas, anom = parse.parsear_municipales(MUNICIPALES)
    assert filas[0]["ganador_partido_norm"] == "X" and filas[0]["fecha"] is not None
    assert filas[1]["afirmativos"] is None and filas[1]["ganador_pct"] is None
    assert {"tipo": "municipal_sin_votos", "cantidad": 1} in anom
    filas, _ = parse.parsear_copia("RESULTADOS CALVO")(CALVO[1:])
    assert filas[0]["datos"]["gob23"] == {"HxC": 0.5, "JxC": 0.2, "LLA": 0.1, "FdT": 0.1, "OTROS": 0.1}
    assert filas[0]["datos"]["segundo_25"] == "DC"
    assert CENTINELA not in str(filas)  # aunque llegara, las posiciones copiadas no la incluyen
    with pytest.raises(parse.EstructuraInvalida):
        parse.parsear_copia("GANADORES")([["LOCALIDAD", "OTRA COSA"]])


def test_rangos_excluyen_intendente_partido_y_habitantes():
    rangos, _ = gsync.rangos_sin_sensibles("RESULTADOS CALVO", CALVO[1], parse.COLUMNAS_EXCLUIDAS)
    assert rangos == ["'RESULTADOS CALVO'!A1:B", "'RESULTADOS CALVO'!F1:AA"]
    rangos, _ = gsync.rangos_sin_sensibles("RESUMEN_VOTOS_CIRCUITOS", RVC[1], parse.COLUMNAS_EXCLUIDAS)
    assert rangos == ["'RESUMEN_VOTOS_CIRCUITOS'!A1:D", "'RESUMEN_VOTOS_CIRCUITOS'!G1:G"]


# ── Sync ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    monkeypatch.setattr(settings, "google_sheet_gob_reuniones_id", "RE")
    monkeypatch.setattr(settings, "google_sheet_gob_elecciones_id", "EL")
    monkeypatch.setattr(settings, "gob_transferencias_sync_enabled", True)


def _parches():
    pedidos: list[str] = []

    def partes(rango: str) -> tuple[str, str]:
        pestana, celdas = rango.split("!")
        return pestana.strip("'"), celdas

    async def get_values(sheet_id, rango, render="FORMATTED_VALUE"):
        pedidos.append(rango)
        pestana, celdas = partes(rango)
        valores = PLANILLAS[(sheet_id, pestana)]
        if ":" in celdas and celdas.split(":")[0].isdigit():
            n = int(celdas.split(":")[0])
            return valores[n - 1 : n]
        return valores

    async def batch_get(sheet_id, rangos, render="FORMATTED_VALUE"):
        out = []
        for rango in rangos:
            pedidos.append(rango)
            pestana, celdas = partes(rango)
            desde, hasta = (gsync_col(x) for x in celdas.replace("1", "").split(":"))
            out.append([fila[desde : hasta + 1] for fila in PLANILLAS[(sheet_id, pestana)]])
        return out

    return (
        patch("app.gob_transferencias.sync.google_sheets.get_values", new=get_values),
        patch("app.gob_transferencias.sync.google_sheets.batch_get_values", new=batch_get),
        pedidos,
    )


async def _nomenclador(db: AsyncSession) -> None:
    db.add_all([
        ExtGobLocalidad(codigo_indec="140001", nombre_gob="L1", departamento_gob="D1", tipo="MU", id_geo="g1"),
        ExtGobLocalidad(codigo_indec="140002", nombre_gob="L2", departamento_gob="D1", tipo="CO", id_geo="g2"),
        ExtGobLocalidad(codigo_indec="140003", nombre_gob="L3", departamento_gob="D2", tipo="MU", id_geo="g3"),
    ])
    await db.commit()


async def _count(db, modelo) -> int:
    return (await db.execute(select(func.count()).select_from(modelo))).scalar_one()


async def _sync(client: AsyncClient):
    p1, p2, pedidos = _parches()
    with p1, p2:
        resultados = {f: await client.post(SYNC, params={"fuente": f}) for f in ("intendentes", "elecciones")}
    return resultados, pedidos


async def test_sync_politico_sin_leer_columnas_excluidas(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    resultados, pedidos = await _sync(client)
    assert all(r.status_code == 200 for r in resultados.values()), {f: r.text for f, r in resultados.items()}
    eleccion = resultados["elecciones"].json()[0]
    assert eleccion["estado"] == "ok"
    assert {"tipo": "circuito_sin_gobierno_local", "cantidad": 1} in eleccion["anomalias"]
    for pestana in ("RESUMEN_VOTOS_CIRCUITOS", "RESULTADOS CALVO", "GANADORES", "RESUMEN_VOTOS"):
        assert f"'{pestana}'!A1:CZ" not in pedidos
    logs = (await db_session.execute(select(ExtGobSyncLog))).scalars().all()
    texto_logs = str([x.anomalias for x in logs])
    assert CENTINELA not in texto_logs and str(TELEFONO) not in texto_logs and "INT A" not in texto_logs
    for modelo in (ExtGobCircuitoLocalidad, ExtGobEleccionCopia):
        assert CENTINELA not in str([vars(x) for x in (await db_session.execute(select(modelo))).scalars()])

    assert await _count(db_session, ExtGobIntendente) == 3
    assert await _count(db_session, ExtGobEleccionCircuito) == 5 + 4 + 1
    assert await _count(db_session, ExtGobEleccionMunicipal) == 2
    assert await _count(db_session, ExtGobEleccionCopia) == 2 + 2 + 2
    codigos = dict((await db_session.execute(select(ExtGobCircuitoLocalidad.circuito_id, ExtGobCircuitoLocalidad.codigo_indec))).all())
    assert codigos == {"1": "140001", "2": "140001", "3A": "140002", "4": "140003"}
    # Segunda corrida: reemplaza sin duplicar.
    await _sync(client)
    assert await _count(db_session, ExtGobEleccionCircuito) == 10


# ── Tablero ───────────────────────────────────────────────────────────────────────


async def test_intendentes(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    r = await client.get(f"{URL}/intendentes")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kpis"] == {"gobiernos_locales": 3, "con_intendente": 3, "reelectos": 1, "continuidad": 2, "con_celular": 2}
    assert {c["clave"]: c["cantidad"] for c in d["por_alineacion"]} == {"PURO": 1, "OPOSICIÓN": 1, "SIN DATO": 1}
    l1 = next(f for f in d["intendentes"] if f["codigo_indec"] == "140001")
    assert l1["celular"] == str(TELEFONO) and l1["alineacion"] == "PURO"
    d2 = (await client.get(f"{URL}/intendentes", params={"codigo_indec": ["140003"]})).json()
    assert [f["codigo_indec"] for f in d2["intendentes"]] == ["140003"]


async def test_elecciones_recalculadas_y_diferencias(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    d = (await client.get(f"{URL}/elecciones")).json()
    assert [e["eleccion"] for e in d["elecciones"]] == ["diputados_2025", "gobernador_2023", "diputados_2023", "diputados_2021"]
    e25 = d["elecciones"][0]
    # Provincia = todos los circuitos, también el que no tiene localidad.
    assert e25["afirmativos"] == 210 and e25["padron"] == 310
    assert d["circuitos_sin_localidad"] == 1
    l1 = next(f for f in e25["por_localidad"] if f["codigo_indec"] == "140001")
    assert (l1["ganador"], l1["segundo"]) == ("PU", "LLA")
    assert l1["margen"] == pytest.approx(10 / 140)
    l2 = next(f for f in e25["por_localidad"] if f["codigo_indec"] == "140002")
    assert l2["ganador"] == "FP"  # ganador sobre todas las fuerzas, no solo las resumidas
    gob = d["elecciones"][1]
    assert gob["fuente"] == "copia" and {c["clave"] for c in gob["localidades_ganadas"]} == {"HxC", "JxC"}
    assert d["municipales"]["sin_votos"] == 1
    var = next(f for f in d["variacion"] if f["codigo_indec"] == "140001")
    assert var["lla_2023"] == pytest.approx(15 / 100) and var["lla_2025"] == pytest.approx(50 / 140)

    dif = {(x["localidad"], x["pestana"], x["campo"]) for x in d["diferencias"]}
    assert ("L1", "RESULTADOS CALVO", "Diputados nacionales 2025 · segundo") in dif
    assert ("L1", "RESULTADOS CALVO", "Diputados nacionales 2025 · % LLA") not in dif
    assert ("L2", "RESULTADOS CALVO", "Diputados nacionales 2025 · % LLA") in dif
    assert ("L2", "RESULTADOS CALVO", "Gobernador 2023 · suma de porcentajes") in dif
    assert ("L3", "RESUMEN_VOTOS", "Diputados nacionales 2025 · votos Otros") in dif
    assert ("L1", "GANADORES", "Diputados nacionales 2025 · ganador") not in dif
    assert ("L3", "GANADORES", "Diputados nacionales 2025 · ganador") not in dif


async def test_politico_solo_admin_y_autoridad_y_seccion_inexistente(client: AsyncClient, as_user):
    assert (await client.get(f"{URL}/nada")).status_code == 404
    as_user(CONSULTA_USER)
    for s in ("intendentes", "elecciones"):
        assert (await client.get(f"{URL}/{s}")).status_code == 403


# ── Padrón único con Privada (spec-padron-politico-gobierno-privada.md) ─────────────

PRIVADA = [
    # L1: actual ya adoptó el de Gobierno; el respaldo tiene el original, en otro orden.
    {"departamento": "D1", "localidad": "L1", "id_geo": "g1", "intendente": "INT A", "partido": "PARTIDO X",
     "intendente_respaldo": "A INT", "partido_respaldo": "LISTA OTRA"},
    # L2: dos filas con el mismo id_geo; la primera sin dato.
    {"departamento": "D1", "localidad": "L2 VIEJO", "id_geo": "g2", "intendente": None, "partido": None,
     "intendente_respaldo": None, "partido_respaldo": None},
    {"departamento": "D1", "localidad": "L2", "id_geo": "g2", "intendente": "INT B SEGUNDO", "partido": "PARTIDO PRIV",
     "intendente_respaldo": "INT B SEGUNDO", "partido_respaldo": "PARTIDO PRIV"},
    {"departamento": "D9", "localidad": "SIN GEO", "id_geo": None, "intendente": "Z", "partido": "Z",
     "intendente_respaldo": "Z", "partido_respaldo": "Z"},
]


async def test_padron_combinado_y_cruce_con_privada(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr("app.integrations.privada_padron.padron_privada", AsyncMock(return_value=PRIVADA))
    await _nomenclador(db_session)
    resultados, _ = await _sync(client)
    log = resultados["intendentes"].json()[0]
    cruce = next(a for a in log["anomalias"] if a["tipo"] == "cruce_privada")
    assert cruce["filas_privada"] == 4
    assert "INT A" not in str(log["anomalias"])  # el log lleva conteos, no nombres

    # Gobierno sin partido en L2: el combinado toma el de Privada.
    i2 = (await db_session.execute(select(ExtGobIntendente).where(ExtGobIntendente.codigo_indec == "140002"))).scalar_one()
    i2.partido = None
    await db_session.commit()

    combinado = {f["codigo_indec"]: f for f in (await client.get("/internal/datos-externos/padron-politico")).json()}
    assert set(combinado) == {"140001", "140002", "140003"}
    assert (combinado["140002"]["partido"], combinado["140002"]["origen_partido"]) == ("PARTIDO PRIV", "privada")
    assert (combinado["140002"]["intendente"], combinado["140002"]["origen_intendente"]) == ("INT B", "gobierno")
    assert "celular" not in str(combinado)

    d = (await client.get(f"{URL}/intendentes")).json()
    l2 = next(f for f in d["intendentes"] if f["codigo_indec"] == "140002")
    assert (l2["partido"], l2["origen_partido"]) == ("PARTIDO PRIV", "privada")
    c = d["cruce"]
    assert c["disponible"] is True
    assert c["por_campo"]["intendente"] == {"igual_otro_orden": 1, "parecido": 1, "solo_gobierno": 1}
    assert c["por_campo"]["partido"] == {"distinto": 1, "solo_privada": 1, "solo_gobierno": 1}
    estados = {(f["localidad"], f["campo"]): f["estado"] for f in c["diferencias"]}
    assert estados[("L1", "partido")] == "distinto" and ("L1", "intendente") not in estados


async def test_privada_caida_deja_lo_anterior(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr("app.integrations.privada_padron.padron_privada", AsyncMock(return_value=PRIVADA))
    await _nomenclador(db_session)
    await _sync(client)
    monkeypatch.setattr("app.integrations.privada_padron.padron_privada", AsyncMock(return_value=None))
    resultados, _ = await _sync(client)
    log = resultados["intendentes"].json()[0]
    assert log["estado"] == "ok" and {"tipo": "privada_no_disponible"} in log["anomalias"]
    assert await _count(db_session, ExtPrivPadronPolitico) == 4


async def test_intendentes_encadena_el_sync_de_privada(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr("app.integrations.privada_padron.padron_privada", AsyncMock(return_value=PRIVADA))
    pedido = AsyncMock(return_value={"filas_actualizadas": 2, "filas_creadas": 0, "campos_cambiados": 3, "otro": 1})
    monkeypatch.setattr("app.integrations.privada_padron.sincronizar_privada", pedido)
    await _nomenclador(db_session)
    resultados, _ = await _sync(client)
    pedido.assert_awaited_once()
    anomalias = resultados["intendentes"].json()[0]["anomalias"]
    assert {"tipo": "privada_sincronizada", "filas_actualizadas": 2, "filas_creadas": 0, "campos_cambiados": 3} in anomalias
