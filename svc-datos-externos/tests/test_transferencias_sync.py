"""Orquestación del sync: upsert idempotente, resolución en batch (ADR-024),
SAVEPOINT por fila, y fail-open cuando la extracción del PDF falla."""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.transferencias import extract, sync as transferencias_sync
from app.transferencias.models import ExtTransferencia, ExtTransferenciaSyncLog

FILAS_JULIO = [
    {"periodo": "2026-07", "tipo": "municipio", "departamento_pdf": "Colón", "nombre_pdf": "Salsipuedes", "concepto": "total", "monto": 1000},
    {"periodo": "2026-07", "tipo": "municipio", "departamento_pdf": "Colón", "nombre_pdf": "Unquillo", "concepto": "total", "monto": 2000},
]


def _mock_extract(filas=None, duplicados=None):
    return patch(
        "app.transferencias.sync.extract.extract_pdf",
        return_value=(filas if filas is not None else FILAS_JULIO, {}, None, duplicados or []),
    )


@pytest.mark.asyncio
async def test_sync_inserta_filas_con_id_geo_resuelto(db_session: AsyncSession):
    with _mock_extract():
        with patch(
            "app.transferencias.sync.geo_resolver.resolver_localidades",
            new=AsyncMock(return_value=[("100", "exacto"), ("200", "fuzzy")]),
        ):
            resultado = await transferencias_sync.sync_desde_pdf(
                db_session, b"%PDF-fake%", "municipio", date(2026, 7, 1)
            )

    assert resultado.filas_procesadas == 2
    assert resultado.filas_sin_match == 0

    filas = (await db_session.execute(select(ExtTransferencia))).scalars().all()
    assert {(f.nombre_pdf, f.id_geo, f.match_tipo) for f in filas} == {
        ("Salsipuedes", "100", "exacto"), ("Unquillo", "200", "fuzzy"),
    }


@pytest.mark.asyncio
async def test_sync_re_correr_mismo_periodo_actualiza_no_duplica(db_session: AsyncSession):
    with _mock_extract():
        with patch(
            "app.transferencias.sync.geo_resolver.resolver_localidades",
            new=AsyncMock(return_value=[(None, None), (None, None)]),
        ):
            await transferencias_sync.sync_desde_pdf(db_session, b"v1", "municipio", date(2026, 7, 1))

    filas_v2 = [dict(f, monto=f["monto"] + 5) for f in FILAS_JULIO]
    with _mock_extract(filas=filas_v2):
        with patch(
            "app.transferencias.sync.geo_resolver.resolver_localidades",
            new=AsyncMock(return_value=[(None, None), (None, None)]),
        ):
            await transferencias_sync.sync_desde_pdf(db_session, b"v2", "municipio", date(2026, 7, 1))

    filas = (await db_session.execute(select(ExtTransferencia))).scalars().all()
    assert len(filas) == 2  # no duplica
    montos = {f.nombre_pdf: float(f.monto) for f in filas}
    assert montos == {"Salsipuedes": 1005, "Unquillo": 2005}  # se actualizó al valor v2


@pytest.mark.asyncio
async def test_sync_cuenta_filas_sin_match(db_session: AsyncSession):
    with _mock_extract():
        with patch(
            "app.transferencias.sync.geo_resolver.resolver_localidades",
            new=AsyncMock(return_value=[(None, None), ("200", "fuzzy")]),
        ):
            resultado = await transferencias_sync.sync_desde_pdf(
                db_session, b"%PDF-fake%", "municipio", date(2026, 7, 1)
            )

    assert resultado.filas_sin_match == 1
    assert any("sin match" in a.lower() or "no matche" in a.lower() for a in resultado.anomalias)


@pytest.mark.asyncio
async def test_sync_reporta_total_duplicado_como_anomalia(db_session: AsyncSession):
    with _mock_extract(duplicados=[("RIO PRIMERO", "Río Primero")]):
        with patch(
            "app.transferencias.sync.geo_resolver.resolver_localidades",
            new=AsyncMock(return_value=[(None, None), (None, None)]),
        ):
            resultado = await transferencias_sync.sync_desde_pdf(
                db_session, b"%PDF-fake%", "municipio", date(2026, 7, 1)
            )

    assert any("RIO PRIMERO" in a for a in resultado.anomalias)


@pytest.mark.asyncio
async def test_extraccion_fallida_se_loguea_y_relanza(db_session: AsyncSession):
    with patch(
        "app.transferencias.sync.extract.extract_pdf",
        side_effect=extract.ExtraccionError("layout inesperado"),
    ):
        with pytest.raises(transferencias_sync.ExtraccionFallida):
            await transferencias_sync.sync_desde_pdf(db_session, b"corrupto", "municipio", date(2026, 7, 1))

    log = (await db_session.execute(select(ExtTransferenciaSyncLog))).scalar_one()
    assert log.filas_procesadas == 0
    assert log.anomalias[0]["tipo"] == "extraccion_fallida"


@pytest.mark.asyncio
async def test_get_last_sync_status_devuelve_la_corrida_mas_reciente(db_session: AsyncSession):
    with _mock_extract():
        with patch(
            "app.transferencias.sync.geo_resolver.resolver_localidades",
            new=AsyncMock(return_value=[(None, None), (None, None)]),
        ):
            await transferencias_sync.sync_desde_pdf(db_session, b"v1", "municipio", date(2026, 6, 1))
            await transferencias_sync.sync_desde_pdf(db_session, b"v2", "municipio", date(2026, 7, 1))

    ultimo = await transferencias_sync.get_last_sync_status(db_session, tipo="municipio")
    assert ultimo.periodo == date(2026, 7, 1)
