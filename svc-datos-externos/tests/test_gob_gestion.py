"""Fase 5: gestión territorial (spec-datos-externos-fase5-gestion-territorial.md §7)."""
from datetime import date
from unittest.mock import patch

from httpx import AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_gestion import parse
from app.gob_gestion.models import ExtGobConvenio, ExtGobObra, ExtGobReunion, ExtGobVisita, ExtGobVisitaGobernador
from app.gob_transferencias import sync as gsync
from app.gobierno.models import ExtGobLocalidad, ExtGobSyncLog
from tests.conftest import CONSULTA_USER
from tests.test_gob_fondos import gsync_col

SYNC = "/internal/datos-externos/gobierno/transferencias/sync"
URL = "/api/v1/datos-externos/tablero/gestion"
SENSIBLE = "PERSONA CENTINELA"
HOY = date(2026, 10, 21)

# 46029 = 2026-01-07; 45500 = 2024-07-27; 47000 = 2028-09-04 (futura).
OBRAS = [
    ["ID_OBRA", "MONTO", "ID_LOC", "TIPO", "LOCALIDAD", "DEPARTAMENTO", "NOMBRE DE OBRA", "DIVISIÓN", "ESTADO DE OBRA",
     "AVANCE", "FECHA INICIO", "FECHA DE FIN DE OBRA", "CATEGORIA"],
    ["HYG-1", 1000.5, 140001, "UNICA", "L1", "D1", "Cloacas", "HYG", "OBRA EN EJECUCION", 0.5, 45500, "2026-04-07", "OBRA EN EJECUCION"],
    ["EPEC-2", 300, 140001, "COMPARTIDA", "L1", "D1", "Línea", "EPEC", "FINALIZADA", 1, "17 jul 2025", "-", "FINALIZADA"],
    ["EPEC-2", 300, 140003, "COMPARTIDA", "L3", "D2", "Línea", "EPEC", "FINALIZADA", 1, "17 jul 2025", "-", "FINALIZADA"],
    ["VIA-3", 9000, "PROVINCIAL", "PROVINCIAL", "PROVINCIAL", "PROVINCIAL", "Ruta", "VIALIDAD", "EN PROYECTO", "-", "-", "-", "A EJECUTAR"],
    ["ARQ-4", 10, "14ZR", "UNICA", "ZONA RURAL - D1", "D1", "Escuela", "ARQUITECTURA", "0", "-", "-", "-", "A EJECUTAR"],
    ["CAS-7", 5, 140002, "#N/A (Did not find value 'CAS-7')", "L2", "D1", "X", "#N/A", "#N/A", "#N/A", "#N/A", "#N/A", "#N/A"],
    ["URB-5", 5, 1, "UNICA", "#N/A", "#N/A", "Plaza", "URBANISMO", "A LICITAR", "-", "-", "-", "A EJECUTAR"],
]
RECORRIDO = [
    ["FUNCIONARIO", "FECHA", "ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "TIPO DE VISITA", "INSTITUCIÓN", "TEMA"],
    ["FUNC A", 45500, 140001, "L1", "D1", "REUNIÓN\xa0DE\xa0TRABAJO", SENSIBLE, SENSIBLE],
    ["FUNC A", 45500, 140001, "L1", "D1", "Institucional", "", ""],  # repetida
    ["FUNC B", 46029, 140002, "L2", "D1", "INSTITUCIONAL", "", SENSIBLE],
    ["FUNC B", 47000, 140003, "L3", "D2", "LANZAMIENTO", "", ""],  # futura
    ["FUNC B", 46029, "#N/A (Did not find value)", "X", "D2", "LANZAMIENTO", "", ""],  # sin código
]
MINISTRO = [RECORRIDO[0], ["MINISTRO", 46029, 140003, "L3", "D2", "Firma convenio", "", SENSIBLE]]
GOBER = [
    ["ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "VISITAS", "INTENDENTE", "PARTIDO", "HABITANTES", "FECHA__ULT"],
    [140001, "L1", "D1", "SI", SENSIBLE, SENSIBLE, "Menos de 2.000", 46029],
    [140002, "L2", "D1", "NO", SENSIBLE, SENSIBLE, "Menos de 2.000", ""],
    [140003, "L3", "D2", "SI", SENSIBLE, SENSIBLE, "Más de 50.000", ""],  # visitada sin fecha
]
REUNIONES = [
    ["ID_REU", "ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "FECHA", "TEMAS", "DETALLE REUNIÓN", "RESOLUCIÓN", "DETALLE RESOLUCIÓN"],
    [1, 140001, "L1", "D1", 45500, "OBRAS, FOCOM", SENSIBLE, "Resuelto", SENSIBLE],
    [2, 140001, "L1", "D1", 45501, "OBRAS", SENSIBLE, "Pendiente", ""],
    [2, "7ZR", "ZONA RURAL", "D2", 45502, "SALUD", "", "", ""],  # id repetido, zona rural
]
CONVENIOS = [
    ["ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "FECHA", "EDUCACION", "INFORMACIÓN", "RADIO", "AÑO RADIO", "BALANCE",
     "POLIDEPORTIVO", "COMPROMISO VOLUNTARIO"],
    [140001, "L1", "D1", "", "SI", "Si", "SI", "2009", "NC", 1, "SI"],
    [140002, "L2", "D1", "", "NO", "si", "SI", "5/22", "NO", 56, ""],
    [140003, "L3", "D2", "", "SI", "NO", "NO", "", "SI", 0, ""],
]

PLANILLAS = {
    ("OB", "BD-TABLERO"): OBRAS, ("RV", "Recorrido"): RECORRIDO, ("RV", "Visitas Gober"): GOBER,
    ("RM", "Recorrido"): MINISTRO, ("RE", "Reuniones"): REUNIONES, ("CO", "Convenios"): CONVENIOS,
}
FUENTES = ("obras", "recorridos", "recorridos_ministro", "reuniones", "convenios")


# ── Parseo puro ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,esperado", [
    (46029, date(2026, 1, 7)), ("1 oct 2026", date(2026, 10, 1)), ("17 jul 2025", date(2025, 7, 17)),
    ("2026-04-07", date(2026, 4, 7)), ("-", None), ("#N/A", None), ("13/5/2026", date(2026, 5, 13)), ("", None),
])
def test_fecha_flexible(raw, esperado):
    assert parse.fecha_flexible(raw) == esperado


def test_parsear_obras():
    filas, anom = parse.parsear_obras(OBRAS)
    assert [f["id_obra"] for f in filas] == ["HYG-1", "EPEC-2", "EPEC-2", "VIA-3", "ARQ-4"]
    prov = filas[3]
    assert prov["ambito"] == "PROVINCIAL" and prov["codigo_indec"] is None and prov["departamento"] is None
    zr = filas[4]
    assert zr["codigo_zona_rural"] == "14ZR" and zr["codigo_indec"] is None and zr["estado"] == parse.SIN_DATO
    assert filas[0]["fecha_inicio"] == date(2024, 7, 27) and filas[0]["fecha_fin"] == date(2026, 4, 7)
    assert filas[1]["fecha_inicio"] == date(2025, 7, 17) and filas[3]["avance"] is None
    tipos = [a["tipo"] for a in anom]
    assert tipos.count("fila_invalida") == 1 and tipos.count("fila_sin_codigo") == 1
    assert {"tipo": "estado_sin_dato", "cantidad": 1} in anom


def test_parsear_recorrido_descarta_futuras_y_sin_codigo():
    filas, anom = parse.parsear_recorrido(parse.ORIGEN_FUNCIONARIOS, hoy=lambda: HOY)(RECORRIDO)
    assert len(filas) == 3 and all(f["origen"] == "funcionarios" for f in filas)
    assert filas[0]["tipo"] == "REUNIÓN DE TRABAJO" and filas[1]["tipo"] == "INSTITUCIONAL"
    assert {"tipo": "visitas_repetidas", "cantidad": 1} in anom
    assert [a.get("motivo") for a in anom if a["tipo"] == "fila_invalida"] == ["fecha_futura"]
    assert sum(1 for a in anom if a["tipo"] == "fila_sin_codigo") == 1


def test_parsear_gobernador_reuniones_y_convenios():
    gob, anom = parse.parsear_visitas_gobernador(GOBER)
    assert [g["visitada"] for g in gob] == [True, False, True] and anom == [{"tipo": "visitada_sin_fecha", "cantidad": 1}]

    reu, anom = parse.parsear_reuniones(REUNIONES)
    assert reu[0]["temas"] == ["OBRAS", "FOCOM"] and reu[2]["codigo_zona_rural"] == "7ZR"
    assert anom == [{"tipo": "id_reunion_repetido", "cantidad": 1}]

    conv, anom = parse.parsear_convenios(CONVENIOS)
    assert {c["convenio"] for c in conv} == {"EDUCACION", "INFORMACIÓN", "RADIO", "BALANCE", "POLIDEPORTIVO", "COMPROMISO VOLUNTARIO"}
    l2 = {c["convenio"]: c for c in conv if c["codigo_indec"] == "140002"}
    assert l2["INFORMACIÓN"]["valor"] == "SI" and l2["POLIDEPORTIVO"]["cantidad"] == 56 and l2["RADIO"]["detalle"] == "5/22"
    assert l2["COMPROMISO VOLUNTARIO"]["valor"] is None
    assert {"tipo": "cantidad_fuera_de_rango", "cantidad": 1} in anom and {"tipo": "anio_radio_no_es_anio", "cantidad": 1} in anom


def test_rangos_excluyen_columnas_por_pestana():
    rangos, _ = gsync.rangos_sin_sensibles("Visitas Gober", GOBER[0], parse.COLUMNAS_EXCLUIDAS["Visitas Gober"])
    assert rangos == ["'Visitas Gober'!A1:D", "'Visitas Gober'!G1:H"]
    rangos, _ = gsync.rangos_sin_sensibles("Reuniones", REUNIONES[0], parse.COLUMNAS_EXCLUIDAS["Reuniones"])
    assert rangos == ["'Reuniones'!A1:F", "'Reuniones'!H1:H"]
    rangos, _ = gsync.rangos_sin_sensibles("Recorrido", RECORRIDO[0], parse.COLUMNAS_EXCLUIDAS["Recorrido"])
    assert rangos == ["'Recorrido'!A1:F"]


# ── Sync ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def config_sync(monkeypatch):
    for fuente, sid in zip(FUENTES, ("OB", "RV", "RM", "RE", "CO")):
        monkeypatch.setattr(settings, f"google_sheet_gob_{fuente}_id", sid)
    monkeypatch.setattr(settings, "gob_transferencias_sync_enabled", True)
    monkeypatch.setattr(gsync, "MIN_LOCALIDADES", 3)


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
            desde, hasta = (gsync_col(x) for x in celdas.replace("1", "").split(":"))
            out.append([fila[desde : hasta + 1] for fila in base[(sheet_id, pestana)]])
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


async def _sync(client: AsyncClient, planillas: dict | None = None):
    p1, p2, pedidos = _parches(planillas)
    resultados = {}
    with p1, p2, patch("app.gob_gestion.parse.date") as d:
        d.today.return_value = HOY
        d.side_effect = lambda *a, **k: date(*a, **k)
        for fuente in FUENTES:
            resultados[fuente] = await client.post(SYNC, params={"fuente": fuente})
    return resultados, pedidos


async def test_sync_gestion_sin_leer_columnas_excluidas(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    resultados, pedidos = await _sync(client)
    assert all(r.status_code == 200 for r in resultados.values()), {f: r.text for f, r in resultados.items()}
    logs = {f: r.json()[0] for f, r in resultados.items()}
    assert {f: log["estado"] for f, log in logs.items()} == {
        "obras": "parcial", "recorridos": "parcial", "recorridos_ministro": "ok", "reuniones": "ok", "convenios": "ok",
    }
    # Nunca se pidió una pestaña entera con columnas excluidas.
    for pestana in ("Recorrido", "Visitas Gober", "Reuniones"):
        assert f"'{pestana}'!A1:CZ" not in pedidos
    todos = (await db_session.execute(select(ExtGobSyncLog))).scalars().all()
    assert SENSIBLE not in str([x.anomalias for x in todos])
    for modelo in (ExtGobVisita, ExtGobVisitaGobernador, ExtGobReunion):
        assert SENSIBLE not in str([vars(x) for x in (await db_session.execute(select(modelo))).scalars()])

    assert await _count(db_session, ExtGobObra) == 5
    assert await _count(db_session, ExtGobVisita) == 3 + 1
    assert await _count(db_session, ExtGobVisitaGobernador) == 3
    assert await _count(db_session, ExtGobReunion) == 3
    assert await _count(db_session, ExtGobConvenio) == 3 * 6


async def test_sync_recorridos_de_las_dos_planillas_no_se_pisan(client: AsyncClient, db_session: AsyncSession):
    await _nomenclador(db_session)
    await _sync(client)
    await _sync(client)  # segunda corrida: reemplaza cada origen por separado
    origenes = (await db_session.execute(select(ExtGobVisita.origen))).scalars().all()
    assert sorted(origenes) == ["funcionarios"] * 3 + ["ministro"]


# ── Tablero ───────────────────────────────────────────────────────────────────────


async def _cargado(client, db_session):
    await _nomenclador(db_session)
    await _sync(client)


async def test_obras_sin_montos_y_por_ambito(client: AsyncClient, db_session: AsyncSession):
    await _cargado(client, db_session)
    r = await client.get(f"{URL}/obras")
    assert r.status_code == 200
    b = r.json()
    assert "monto" not in r.text
    assert b["kpis"]["obras"] == 4 and b["kpis"]["en_ejecucion"] == 1 and b["kpis"]["finalizadas"] == 1
    linea = next(o for o in b["obras"] if o["id_obra"] == "EPEC-2")
    assert linea["departamentos"] == ["D1", "D2"] and [l["codigo"] for l in linea["localidades"]] == ["140001", "140003"]
    # Una obra compartida cuenta una vez en cada departamento.
    assert {d["departamento"]: d["obras"] for d in b["por_departamento"]} == {"D1": 3, "D2": 1}
    # Con filtro: solo las que tocan la localidad, sin provinciales.
    f = (await client.get(f"{URL}/obras", params={"codigo_indec": ["140003"]})).json()
    assert [o["id_obra"] for o in f["obras"]] == ["EPEC-2"]


async def test_visitas_cobertura_y_funcionarios(client: AsyncClient, db_session: AsyncSession):
    await _cargado(client, db_session)
    b = (await client.get(f"{URL}/visitas")).json()
    c = b["gestion"]["cobertura"]
    assert (c["total"], c["visitadas"], c["municipios"], c["municipios_visitados"], c["comunas_visitadas"]) == (3, 3, 2, 2, 1)
    assert b["anios"] == [2024, 2026]
    a2024 = next(a for a in b["por_anio"] if a["anio"] == 2024)["periodo"]
    assert a2024["visitas"] == 2 and a2024["cobertura"]["visitadas"] == 1 and a2024["mensual"][6] == 2
    func = {f["funcionario"]: f for f in b["gestion"]["por_funcionario"]}
    assert func["FUNC A"]["actividades"] == 2 and func["FUNC A"]["localidades"] == 1 and func["MINISTRO"]["municipios"] == 1
    assert b["ultima_fecha"] == {"funcionarios": "2026-01-07", "ministro": "2026-01-07"}
    assert SENSIBLE not in str(b)


async def test_visitas_gobernador_reuniones_y_convenios(client: AsyncClient, db_session: AsyncSession):
    await _cargado(client, db_session)
    g = (await client.get(f"{URL}/visitas-gobernador")).json()
    assert g["cobertura"]["visitadas"] == 2 and g["cobertura"]["comunas_visitadas"] == 0
    assert {r["rango"]: (r["total"], r["visitadas"]) for r in g["por_rango"]} == {"Menos de 2.000": (2, 1), "Más de 50.000": (1, 1)}
    assert "INTENDENTE" not in str(g).upper() and SENSIBLE not in str(g)

    r = (await client.get(f"{URL}/reuniones")).json()
    assert r["gestion"]["reuniones"] == 3 and r["ultima_fecha"] == "2024-07-29"
    assert {t["clave"]: t["cantidad"] for t in r["gestion"]["por_tema"]} == {"OBRAS": 2, "FOCOM": 1, "SALUD": 1}
    l1 = next(x for x in r["gestion"]["por_localidad"] if x["codigo"] == "140001")
    assert l1["reuniones"] == 2 and l1["pendientes"] == 1

    c = (await client.get(f"{URL}/convenios")).json()
    res = {x["convenio"]: x for x in c["resumen"]}
    assert res["EDUCACION"]["si"] == 2 and res["BALANCE"]["nc"] == 1 and res["POLIDEPORTIVO"]["cantidad"] == 57
    assert res["COMPROMISO VOLUNTARIO"]["sin_dato"] == 2

    inicio = (await client.get("/api/v1/datos-externos/tablero/inicio", params={"anio": 2026})).json()
    assert inicio["gestion"] == {
        "visitas": 4, "localidades_visitadas": 3, "reuniones": 3, "localidades_con_reunion": 1,
        "gobernador_visitadas": 2, "gobernador_total": 3,
    }


async def test_gestion_solo_admin_y_autoridad_y_seccion_inexistente(client: AsyncClient, as_user):
    assert (await client.get(f"{URL}/nada")).status_code == 404
    as_user(CONSULTA_USER)
    for s in ("obras", "visitas", "visitas-gobernador", "reuniones", "convenios"):
        assert (await client.get(f"{URL}/{s}")).status_code == 403
