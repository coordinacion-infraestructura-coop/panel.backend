"""Tests del sync de la hoja "BD" (compromisos ATP + cronograma de pago)."""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp import sync as atp_sync
from app.atp.models import AtpCompromiso, AtpCronogramaPago, AtpSyncLog

# ── Fixtures de hoja, con los mismos problemas de calidad de datos reales ──────
# Encabezado de columna A es un espacio en blanco en el Sheet real (columna
# "#"), se incluye "Enero 28" a propósito: NO es uno de los 34 meses
# "conocidos" al momento del análisis — prueba que el parseo de cronograma es
# genérico por patrón de encabezado, no una lista fija.

HEADERS_BD = [
    " ", "DEPARTAMENTO", "LOCALIDAD", "Ministerio", "Fecha de anuncio",
    "Nro. Expediente", "Derivado", "Monto", "Destino", "SALDO ATP",
    "Marzo 25", "Abril 25", "Enero 28", "IGNORAR", "CUOTA SIN ASIGNAR",
]

ROW_COMPROMISO_GOBIERNO = [
    "1", "CALAMUCHITA", "EMBALSE", "Gobierno", "19/09/2026", "",
    False, "150000000", "ADOQUINADO", "0", "", "-30000000", "-50000000", "", "0",
]

ROW_COMPROMISO_DERIVADO = [
    "2", "CRUZ DEL EJE", "GUANACO MUERTO", "Cooperativas y Mutuales",
    "24/02/2026", "0423-079111/2026", True, "50000000",
    "Programa Provincial de Cordón Cuneta y Adoquines", "0", "", "", "", "", "0",
]

ROW_SIN_MONTO_NI_FECHA = [
    "3", "SAN ALBERTO", "ARROYO DE LOS PATOS", "Gobierno", "", "",
    False, "", "instituciones", "0", "", "", "", "", "0",
]

ROW_BLANK: list = []


def _mock_sheet(rows):
    """Responde siempre con `rows` — soporta llamar sync_from_sheet() varias
    veces dentro del mismo `with` (ej. tests de idempotencia)."""
    return patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(return_value=rows),
    )


# ── Parseo de campos fijos ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_inserta_compromiso_y_parsea_campos_fijos(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_GOBIERNO]):
        result = await atp_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1
    assert result.filas_insertadas == 1
    assert result.filas_error == 0

    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    assert compromiso.departamento == "CALAMUCHITA"
    assert compromiso.localidad == "EMBALSE"
    assert compromiso.ministerio_destino == "Gobierno"
    assert compromiso.fecha_anuncio == date(2026, 9, 19)
    assert compromiso.derivado is False
    assert compromiso.monto == 150000000
    assert compromiso.destino == "ADOQUINADO"
    assert compromiso.saldo_atp == 0
    assert compromiso.sheet_row_number == 6  # header_row(5) + 1 + offset(0)


@pytest.mark.asyncio
async def test_sync_parsea_derivado_y_expediente(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_DERIVADO]):
        await atp_sync.sync_from_sheet(db_session)

    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    assert compromiso.derivado is True
    assert compromiso.ministerio_destino == "Cooperativas y Mutuales"
    assert compromiso.nro_expediente == "0423-079111/2026"


@pytest.mark.asyncio
async def test_sync_tolera_monto_y_fecha_vacios(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW_SIN_MONTO_NI_FECHA]):
        result = await atp_sync.sync_from_sheet(db_session)

    assert result.filas_error == 0
    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    assert compromiso.monto is None
    assert compromiso.fecha_anuncio is None


# ── Cronograma de pago mensual (parseo genérico por patrón de encabezado) ────

@pytest.mark.asyncio
async def test_sync_cronograma_parsea_meses_incluyendo_uno_no_hardcodeado(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_GOBIERNO]):
        await atp_sync.sync_from_sheet(db_session)

    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    cronograma = {
        c.periodo: float(c.monto)
        for c in (
            await db_session.execute(
                select(AtpCronogramaPago).where(AtpCronogramaPago.compromiso_id == compromiso.id)
            )
        ).scalars().all()
    }
    # "Marzo 25" vino vacío en la fila -> no se persiste una fila en 0.
    assert date(2025, 3, 1) not in cronograma
    assert cronograma[date(2025, 4, 1)] == -30000000.0
    # "Enero 28" no es uno de los 34 meses "conocidos" al momento del
    # análisis -> el parseo genérico por patrón lo toma igual.
    assert cronograma[date(2028, 1, 1)] == -50000000.0


@pytest.mark.asyncio
async def test_sync_ignora_columnas_de_ajuste(db_session: AsyncSession):
    """IGNORAR / CUOTA SIN ASIGNAR no matchean el patrón de mes -> se descartan."""
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_GOBIERNO]):
        await atp_sync.sync_from_sheet(db_session)

    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    cronograma = (
        await db_session.execute(
            select(AtpCronogramaPago).where(AtpCronogramaPago.compromiso_id == compromiso.id)
        )
    ).scalars().all()
    assert len(cronograma) == 2  # solo Abril 25 y Enero 28 (Marzo 25 vacío)


# ── Filas en blanco / idempotencia ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_ignora_filas_en_blanco(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW_BLANK, ROW_COMPROMISO_GOBIERNO]):
        result = await atp_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1


@pytest.mark.asyncio
async def test_sync_repetido_actualiza_no_duplica_y_reemplaza_cronograma(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_GOBIERNO]):
        r1 = await atp_sync.sync_from_sheet(db_session)

    row_actualizada = list(ROW_COMPROMISO_GOBIERNO)
    row_actualizada[11] = "-100000000"  # Abril 25 cambia de valor en una nueva corrida
    with _mock_sheet([HEADERS_BD, row_actualizada]):
        r2 = await atp_sync.sync_from_sheet(db_session)

    assert r1.filas_insertadas == 1
    assert r2.filas_insertadas == 0
    assert r2.filas_actualizadas == 1

    compromisos = (await db_session.execute(select(AtpCompromiso))).scalars().all()
    assert len(compromisos) == 1

    cronograma = (
        await db_session.execute(
            select(AtpCronogramaPago).where(AtpCronogramaPago.compromiso_id == compromisos[0].id)
        )
    ).scalars().all()
    abril = next(c for c in cronograma if c.periodo == date(2025, 4, 1))
    assert float(abril.monto) == -100000000.0  # reemplazado, no duplicado


# ── Log de sincronización ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_registra_log_con_contadores(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_GOBIERNO, ROW_COMPROMISO_DERIVADO]):
        await atp_sync.sync_from_sheet(db_session, triggered_by="cloud-scheduler")

    log = (await db_session.execute(select(AtpSyncLog))).scalar_one()
    assert log.filas_leidas == 2
    assert log.filas_insertadas == 2
    assert log.filas_error == 0
    assert log.triggered_by == "cloud-scheduler"
    assert log.finished_at is not None


def _row(localidad: str) -> list:
    row = list(ROW_COMPROMISO_GOBIERNO)
    row[2] = localidad
    return row


@pytest.mark.asyncio
async def test_error_de_fila_no_envenena_las_filas_siguientes(db_session: AsyncSession):
    """Aislamiento por SAVEPOINT desde el día uno (lección de
    spec-sync-cc-checklist-tecnico.md §13.5): un error real de DB en la fila
    del medio de un batch no debe frenar el resto ni impedir el log final."""
    real_upsert = atp_sync._upsert_compromiso
    calls = {"n": 0}

    async def fake_upsert(db, sheet_row_number, r):
        calls["n"] += 1
        if calls["n"] == 2:
            now = datetime.now(timezone.utc)
            db.add(AtpCompromiso(id="dup-a", sheet_row_number=999, last_synced_at=now))
            db.add(AtpCompromiso(id="dup-a", sheet_row_number=998, last_synced_at=now))
            await db.flush()  # IntegrityError real: primary key duplicada
            return True
        return await real_upsert(db, sheet_row_number, r)

    rows = [HEADERS_BD, _row("Localidad Uno"), _row("Localidad Dos"), _row("Localidad Tres")]
    with _mock_sheet(rows), patch(
        "app.atp.sync._upsert_compromiso", new=AsyncMock(side_effect=fake_upsert)
    ):
        result = await atp_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 3
    assert result.filas_error == 1
    assert result.filas_insertadas == 2

    log = (await db_session.execute(select(AtpSyncLog))).scalar_one()
    assert log.filas_insertadas == 2
    assert log.finished_at is not None


@pytest.mark.asyncio
async def test_sync_falla_total_queda_logueada_y_relanza(db_session: AsyncSession):
    with patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(side_effect=RuntimeError("API deshabilitada")),
    ):
        with pytest.raises(atp_sync.SheetReadError):
            await atp_sync.sync_from_sheet(db_session, triggered_by="cloud-scheduler")

    log = (await db_session.execute(select(AtpSyncLog))).scalar_one()
    assert log.filas_error == 1
    assert log.filas_leidas == 0
    assert "API deshabilitada" in log.errores
    assert log.triggered_by == "cloud-scheduler"
