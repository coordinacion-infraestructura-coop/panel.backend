from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import rollup
from app.geo_censo.models import ExtGeoCenso
from app.transferencias.models import ExtTransferencia


@pytest.mark.asyncio
async def test_rollup_combina_censo_y_ultimo_periodo_de_transferencias(db_session: AsyncSession):
    db_session.add(ExtGeoCenso(
        id="c1", id_geo="100", codigo_indec="140001", categoria="MU",
        departamento_censo="Colón", localidad_censo="Salsipuedes",
        poblacion_2022=15000, viviendas_2022=6000,
    ))
    db_session.add_all([
        ExtTransferencia(
            periodo=date(2026, 6, 1), tipo="municipio", id_geo="100",
            nombre_pdf="Salsipuedes", departamento_pdf="Colón", concepto="total", monto=900,
        ),
        ExtTransferencia(
            periodo=date(2026, 7, 1), tipo="municipio", id_geo="100",
            nombre_pdf="Salsipuedes", departamento_pdf="Colón", concepto="coparticipacion_ley_8663", monto=800,
        ),
        ExtTransferencia(
            periodo=date(2026, 7, 1), tipo="municipio", id_geo="100",
            nombre_pdf="Salsipuedes", departamento_pdf="Colón", concepto="fasamu", monto=200,
        ),
    ])
    await db_session.flush()

    resultado = await rollup.rollup_territorial(db_session)

    assert len(resultado) == 1
    r = resultado[0]
    assert r["id_geo"] == "100"
    assert r["poblacion_2022"] == 15000
    assert r["transferencias_periodo"] == "2026-07-01"  # el más reciente, no junio
    assert r["transferencias_total"] == 1000.0  # 800 + 200, sin contar concepto "total" si existiera
    assert r["transferencias_por_concepto"] == {"coparticipacion_ley_8663": 800.0, "fasamu": 200.0}


@pytest.mark.asyncio
async def test_rollup_sin_transferencias_devuelve_censo_solo(db_session: AsyncSession):
    db_session.add(ExtGeoCenso(
        id="c2", id_geo="200", codigo_indec="140002", categoria="CO",
        departamento_censo="Pocho", localidad_censo="Salsacate",
        poblacion_2022=500, viviendas_2022=250,
    ))
    await db_session.flush()

    resultado = await rollup.rollup_territorial(db_session)
    assert resultado == [{
        "id_geo": "200", "codigo_indec": "140002", "categoria": "CO",
        "poblacion_2022": 500, "viviendas_2022": 250,
        "transferencias_periodo": None, "transferencias_total": None, "transferencias_por_concepto": None,
    }]


@pytest.mark.asyncio
async def test_rollup_ignora_censo_sin_id_geo(db_session: AsyncSession):
    db_session.add(ExtGeoCenso(
        id="c3", id_geo=None, codigo_indec="140003", categoria="CO",
        departamento_censo=None, localidad_censo="Sin Match", match_tipo="sin_match",
    ))
    await db_session.flush()

    resultado = await rollup.rollup_territorial(db_session)
    assert resultado == []


@pytest.mark.asyncio
async def test_rollup_incluye_transferencias_sin_fila_de_censo(db_session: AsyncSession):
    """Bug real de producción (2026-10-01): una localidad cuya fila de Censo
    quedó ambigua/sin `id_geo` (el Cuadro 1.6 no trae departamento, dos
    localidades homónimas en deptos distintos no se pueden desambiguar) pero
    cuyas transferencias SÍ matchearon bien (el PDF de transferencias sí trae
    departamento) no debe desaparecer del rollup — antes se perdía porque el
    rollup sólo iteraba sobre las filas de censo con id_geo resuelto."""
    db_session.add(ExtGeoCenso(
        id="c4", id_geo=None, codigo_indec="140099", categoria="MU",
        departamento_censo=None, localidad_censo="Agua de Oro", match_tipo="ambiguo",
    ))
    db_session.add_all([
        ExtTransferencia(
            periodo=date(2026, 7, 1), tipo="municipio", id_geo="22", codigo_indec="140022",
            nombre_pdf="Agua de Oro", departamento_pdf="Colón", concepto="coparticipacion_ley_8663", monto=100,
        ),
        ExtTransferencia(
            periodo=date(2026, 7, 1), tipo="municipio", id_geo="22", codigo_indec="140022",
            nombre_pdf="Agua de Oro", departamento_pdf="Colón", concepto="fasamu", monto=50,
        ),
    ])
    await db_session.flush()

    resultado = await rollup.rollup_territorial(db_session)

    assert len(resultado) == 1
    r = resultado[0]
    assert r["id_geo"] == "22"
    assert r["poblacion_2022"] is None  # censo nunca resolvió este id_geo
    assert r["codigo_indec"] == "140022"  # sacado de transferencias, no de censo
    assert r["categoria"] == "MU"
    assert r["transferencias_total"] == 150.0
