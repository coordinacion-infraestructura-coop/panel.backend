from sqlalchemy import select

from app.etl.carga import refrescar
from app.semantica.models import (
    AgAtpPago, AgFrescura, AgGestion, AgHito, AgLocalidad, AgMovimiento, AgProgramaItem, AgTransferencia,
)
from tests.conftest import HOY, lector_de, raw_fuentes


async def _todos(db, modelo):
    return (await db.execute(select(modelo))).scalars().all()


async def test_carga_completa(cargado):
    db = cargado
    locs = {l.id_geo: l for l in await _todos(db, AgLocalidad)}
    assert len(locs) == 5
    sf = locs["G1"]
    assert (sf.poblacion, sf.intendente, sf.partido) == (70000, "Intendente SF", "Partido A")
    assert sf.url_ficha == "/resumen-territorial/San%20Justo/San%20Francisco"

    items = {i.id: i for i in await _todos(db, AgProgramaItem)}
    cc1 = items["cc:cc1"]
    # nombres oficiales del padrón, no el texto del panel
    assert (cc1.departamento, cc1.localidad) == ("San Justo", "San Francisco")
    assert cc1.estado_normalizado == "En ejecución"
    assert cc1.estado_tecnico == "En obra" and cc1.avance == 0.7
    # anticipo (50 %) + 40 (25 %) acreditados sobre 1.000.000
    assert cc1.monto_ejecutado == 750000
    assert items["cc:cc2"].estado_normalizado == "Finalizado"


async def test_gas_prorratea_monto_entre_localidades(cargado):
    gas = [i for i in await _todos(cargado, AgProgramaItem) if i.programa == "gas_obra"]
    assert len(gas) == 3 and {g.origen_id for g in gas} == {"o1"}
    assert round(sum(g.monto for g in gas), 2) == 900
    assert round(sum(g.monto_usd for g in gas), 2) == 9
    sin_vinculo = next(g for g in gas if g.id_geo is None)
    assert sin_vinculo.localidad == "Frontera"  # texto de origen cuando no hay vínculo


async def test_atp_entregado_y_pagos_separados(cargado):
    atp = next(i for i in await _todos(cargado, AgProgramaItem) if i.programa == "atp")
    assert atp.monto_ejecutado == 400 and atp.estado_origen == "Parcial"
    pagos = await _todos(cargado, AgAtpPago)
    assert {p.fuente for p in pagos} == {"compromiso", "interno"}
    interno = next(p for p in pagos if p.fuente == "interno")
    assert interno.id_geo == "G1"  # vía codigo_indec del censo
    assert next(p for p in pagos if p.fuente == "compromiso").monto == 400  # valor absoluto


async def test_privada_enmascara_y_calcula_dias(cargado):
    g = {x.id: x for x in await _todos(cargado, AgGestion)}
    assert "351-555-1234" not in g["p1"].detalle and "30.123.456" not in g["p1"].detalle
    assert "juan@mail.com" not in g["p1"].detalle and "$ 1.500.000" in g["p1"].detalle
    assert g["p1"].dias_abierta == (HOY - g["p1"].fecha_ingreso).days
    assert g["p2"].dias_abierta is None  # finalizada
    assert g["p3"].id_geo is None and g["p3"].localidad == "Pueblo X"  # id_geo inexistente se descarta
    assert (g["p1"].departamento, g["p1"].localidad) == ("San Justo", "San Francisco")


async def test_hitos_y_movimientos(cargado):
    hitos = await _todos(cargado, AgHito)
    assert {h.id for h in hitos} == {"h1", "h2", "h3"}  # el de la entidad borrada se descarta
    movs = await _todos(cargado, AgMovimiento)
    assert {m.programa for m in movs} == {"cc", "privada"}
    assert any(m.dimension == "tecnico" and m.estado_nuevo == "En obra" for m in movs)


async def test_fuente_caida_conserva_datos_previos(cargado):
    db = cargado
    raw = raw_fuentes()
    raw["gasifera"]["obras"] = []  # si se leyera, borraría las obras
    raw["datos_externos"]["censo"] = []
    estado = await refrescar(db, lector_de(raw, fallan={"gasifera", "datos_externos"}), hoy=HOY)
    await db.commit()
    assert estado["gasifera"]["estado"] == "error" and estado["vivienda"]["estado"] == "ok"
    assert len([i for i in await _todos(db, AgProgramaItem) if i.programa == "gas_obra"]) == 3
    assert len(await _todos(db, AgTransferencia)) == 2
    sf = await db.get(AgLocalidad, "G1")
    assert sf.poblacion == 70000  # el censo previo se conserva
    fr = await db.get(AgFrescura, "gasifera")
    assert fr.estado == "error" and "caída" in fr.mensaje and fr.ultimo_dato is not None


async def test_fuente_sin_configurar(db):
    estado = await refrescar(db)  # sin URLs en settings
    assert all(e["estado"] == "sin_configurar" for e in estado.values())


async def test_transferencias_no_cargan_la_fila_total(cargado):
    from sqlalchemy import func, select
    from app.semantica.models import AgTransferencia
    total = (await cargado.execute(select(func.sum(AgTransferencia.monto)))).scalar()
    conceptos = {c for (c,) in (await cargado.execute(select(AgTransferencia.concepto)))}
    assert total == 150 and "total" not in conceptos
