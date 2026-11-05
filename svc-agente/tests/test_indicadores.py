from datetime import date

import pytest

from app.agente import indicadores as ind


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(ind, "_hoy", lambda: date(2026, 11, 5))


async def test_resolver_territorio(cargado):
    db = cargado
    assert (await ind.resolver_territorio(db, "toda la provincia"))["tipo"] == "provincia"
    r = await ind.resolver_territorio(db, "depto San Justo")
    assert r == {"tipo": "departamento", "departamento": "San Justo"}
    assert (await ind.resolver_territorio(db, "General San Martin"))["departamento"] == "General San Martín"
    assert (await ind.resolver_territorio(db, "villa maria"))["id_geo"] == "G3"
    assert (await ind.resolver_territorio(db, "San Fco"))["id_geo"] == "G1"  # alias manual
    amb = await ind.resolver_territorio(db, "Villa del Rosario")  # homónimas: nunca adivina
    assert amb["tipo"] == "ambiguo" and {c["id_geo"] for c in amb["candidatos"]} == {"G4", "G5"}
    cerca = await ind.resolver_territorio(db, "Morterso")
    assert cerca["id_geo"] == "G2" and "aviso" in cerca
    assert (await ind.resolver_territorio(db, "Narnia"))["tipo"] == "sin_resultado"


async def test_estado_programa_departamento(cargado):
    r = await ind.estado_programa_territorio(cargado, None, departamento="San Justo")
    progs = {p["programa"]: p for p in r["programas"]}
    assert set(progs) == {"cc", "gas_obra", "atp"}
    assert progs["cc"]["total"] == 2
    assert progs["cc"]["por_estado_normalizado"]["Finalizado"] == 1
    assert progs["cc"]["pct_finalizado"] == 50.0
    assert progs["cc"]["monto_total_pesos"] == 1500000
    # la obra de gas cuenta una vez aunque esté en tres localidades del depto (una sin vínculo:
    # toma el departamento de la obra), y el monto prorrateado suma el total
    assert progs["gas_obra"]["total"] == 1 and progs["gas_obra"]["monto_total_pesos"] == 900
    assert r["ultimos_movimientos"][0]["dimension"] == "tecnico"
    assert any(b["tipo"] == "tabla" for b in r["bloques"])


async def test_estado_programa_localidad_trae_contexto(cargado):
    r = await ind.estado_programa_territorio(cargado, "cc", id_geo="G1")
    ctx = r["contexto_localidad"]
    assert ctx == {"localidad": "San Francisco", "departamento": "San Justo", "poblacion": 70000,
                   "intendente": "Intendente SF", "partido": "Partido A",
                   "url_ficha": "/resumen-territorial/San%20Justo/San%20Francisco"}
    assert any(b["tipo"] == "link" for b in r["bloques"])


async def test_ficha_localidad(cargado):
    r = await ind.ficha_territorio(cargado, id_geo="G1")
    assert r["gestiones_privada"] == {"total": 2, "abiertas": 1, "por_estado": {"INGRESADO": 1, "FINALIZADA": 1}}
    assert r["transferencias_ultimo_anio"]["total"] == 150
    atp = r["atp"]
    assert atp["compromisos_gobernador"] == {"compromisos": 1, "anunciado": 1000, "entregado": 400}
    assert atp["atp_interno_ultimo_anio"] == {"pagos": 1, "monto": 250}
    assert {f["fuente"] for f in r["fuentes"]} >= {"Vivienda", "Privada"}


async def test_ficha_departamento(cargado):
    r = await ind.ficha_territorio(cargado, departamento="San Justo")
    assert r["contexto"] == {"departamento": "San Justo", "localidades": 2, "poblacion": 70000}
    assert (await ind.ficha_territorio(cargado))["error"]


async def test_montos(cargado):
    r = await ind.montos(cargado, None, departamento="San Justo")
    progs = {p["programa"]: p for p in r["programas"]}
    assert progs["cc"]["comprometido_pesos"] == 1500000 and progs["cc"]["ejecutado_pesos"] == 750000
    assert progs["cc"]["ratio_ejecutado_pct"] == 50.0
    assert progs["gas_obra"]["ejecutado_pesos"] is None and progs["gas_obra"]["monto_usd"] == 9
    assert progs["transferencias"]["transferido_pesos"] == 150
    # período por fecha de inicio
    r2 = await ind.montos(cargado, "ch", desde="2026-01-01", hasta="2026-12-31")
    assert r2["programas"][0]["comprometido_pesos"] == 340000000


async def test_pendientes_gestiones(cargado):
    r = await ind.pendientes(cargado, "gestiones", 90)
    assert r["abiertas"] == 2 and r["sobre_umbral"] == 1
    assert r["ranking_area"][0]["nombre"] == "Salud"
    assert "351-555-1234" not in r["mas_antiguas"][0]["detalle"]


async def test_pendientes_programas_y_hitos(cargado):
    r = await ind.pendientes(cargado, "programas", 60)
    nombres = {d["nombre"] for d in r["detalle"]}
    assert "SAN FRANCISCO" in nombres and "Morteros" not in nombres  # finalizado no cuenta
    h = await ind.pendientes(cargado, "hitos", departamento="San Justo")
    assert h["hitos_sin_acreditar"] == 1 and h["monto_pendiente"] == 250000
