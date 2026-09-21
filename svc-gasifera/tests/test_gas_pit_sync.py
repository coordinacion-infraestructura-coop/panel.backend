"""Tests del sync del Sheet "SEC. GAS PIT" (obras de gas + acciones territoriales)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gas_pit import sync as gas_pit_sync
from app.gas_pit.models import (
    GasPitAccionTerritorio,
    GasPitObra,
    GasPitObraLocalidad,
    GasPitSyncLog,
)

# ── Fixtures de hojas, con los mismos problemas de calidad de datos reales ─────

MATRIZ_HEADERS = [
    "SPIP", "EXPEDIENTE", "DIVISIÓN", "NOMBRE DE OBRA", "T. OBRA", "SUB-TIPO DE OBRA",
    "CONTRATISTA", "ESTADO DE OBRA", "LOCALIDAD", "DEPARTAMENTO", "AVANCE",
    "REPLA. INICIAL", "FECHA LIC", "VENCIMIENTO", "PLAZO VIGENTE EN DÍAS",
    "PLAZO ORIGINAL", "CONTRATO BASE", "AMPLIACION", "ENMIENDA",
    "IMPORTE DE OBRA ACTUALIZADO", "IMPORTE EN DÓLAR", "PRIORIDAD", "CATEGORIA",
    "REGION", "AUTORIZADA 2025", "DEPARTAMENTO MAPA", "ID-DEPARTAMENTO", "PIT",
    "ESTADO-RESUMEN",
]

ROW_OBRA_GAS = [
    "5661", "0632-005637/2022", "HYG", "PROVISION DE GAS VIRTUAL A HUANCHILLA",
    "GASODUCTOS", "E- OBRAS DE GAS", "HUGO DEL CARMEN OJEDA S A", "OBRA EN EJECUCION",
    "HUANCHILLA", "JUAREZ CELMAN", "0.7986", "", "", "", "", "", "1000000", "0", "0",
    "1000000", "684", "OBRAS CON PRESUPUESTO", "2", "CENTRO", "SI", "JUAREZ CELMAN",
    "5", "NO PIT", "EN EJECUCIÓN",
]

ROW_OBRA_GAS_MULTI_LOCALIDAD = [
    "-", "-", "HYG", "RED DE GAS ZONA NOROESTE", "GASODUCTOS", "E- OBRAS DE GAS",
    "", "PROC. DE ADJUDICACION", "TANTI - EL DURAZNO", "PUNILLA", "0", "", "", "",
    "", "", "", "", "", "", "", "PENDIENTE", "3", "NOROESTE", "PEDIR AUTORIZACIÓN",
    "PUNILLA", "12", "PIT", "A EJECUTAR",
]

ROW_OBRA_VIAL_FUERA_DE_ALCANCE = [
    "412", "0045-025708/2023", "VIALIDAD", "ACCESO A VILLA CONCEPCIÓN DEL TIO",
    "ACCESO", "A- OBRAS VIALES", "CORBE S.R.L.", "OBRA EN EJECUCION",
    "VILLA CONCEPCIÓN DEL TÍO", "SAN JUSTO", "0.996", "", "", "", "", "", "", "", "",
    "", "", "OBRAS CON PRESUPUESTO", "2", "CENTRO", "SI", "SAN JUSTO", "20", "NO PIT",
    "EN EJECUCIÓN",
]

ROW_OBRA_BLANK: list = []

ACCIONES_HEADERS = [
    "Fecha", "Departamento", "Localidad", "Ministerio", "Área", "",
    "ID_ACCION", "Acción", "Detalle de la acción", "Estado",
    "Monto Inversión solicitado", "Comentarios", "Monto Inversión USD",
    "ALERTA_LOCALIDAD", "DEPTO_SUGERIDO",
]

ROW_ACCION_CUMPLIDA = [
    "01/03/2026", "Juárez Celman", "Huanchilla", "Cooperativas y mutuales",
    "Secretaría Gas", "", "A-1", "Red de gas", "Segunda etapa red de gas",
    "Cumplido", "1000000", "Inaugurado", "", "OK", "",
]

ROW_ACCION_SIN_LOCALIDAD_NI_ACCION: list = ["02/03/2026", "Punilla"]


def _mock_sheet(matriz_rows, acciones_rows):
    """Responde según el rango pedido (no una lista de side_effects que se agota
    tras la primera corrida) — soporta llamar sync_from_sheet() varias veces
    dentro del mismo `with` (ej. tests de idempotencia)."""

    async def fake_get_values(spreadsheet_id, range_name):
        return matriz_rows if range_name.startswith("MATRIZ") else acciones_rows

    return patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(side_effect=fake_get_values),
    )


# ── MATRIZ (NO TOMAR): filtro por sub-tipo + normalización ─────────────────────

@pytest.mark.asyncio
async def test_sync_inserta_obra_de_gas_y_filtra_otras_categorias(db_session: AsyncSession):
    with _mock_sheet(
        [MATRIZ_HEADERS, ROW_OBRA_GAS, ROW_OBRA_VIAL_FUERA_DE_ALCANCE],
        [ACCIONES_HEADERS],
    ):
        result = await gas_pit_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1  # la vial no cuenta, está fuera de alcance
    assert result.filas_insertadas == 1
    assert result.filas_error == 0

    obras = (await db_session.execute(select(GasPitObra))).scalars().all()
    assert len(obras) == 1
    assert obras[0].nombre_obra == "PROVISION DE GAS VIRTUAL A HUANCHILLA"
    assert obras[0].sub_tipo_obra == "E- OBRAS DE GAS"
    assert obras[0].estado_obra == "OBRA EN EJECUCION"
    assert float(obras[0].avance) == pytest.approx(0.7986)
    assert obras[0].pit is False
    assert obras[0].categoria == 2


@pytest.mark.asyncio
async def test_sync_normaliza_enum_casi_duplicado_y_spip_ambiguo(db_session: AsyncSession):
    with _mock_sheet([MATRIZ_HEADERS, ROW_OBRA_GAS_MULTI_LOCALIDAD], [ACCIONES_HEADERS]):
        await gas_pit_sync.sync_from_sheet(db_session)

    obra = (await db_session.execute(select(GasPitObra))).scalar_one()
    assert obra.estado_obra == "EN PROCESO DE ADJUDICACIÓN"  # normalizado desde "PROC. DE ADJUDICACION"
    assert obra.spip is None  # "-" -> NULL
    assert obra.pit is True

    localidades = {
        l.localidad
        for l in (
            await db_session.execute(
                select(GasPitObraLocalidad).where(GasPitObraLocalidad.obra_id == obra.id)
            )
        ).scalars().all()
    }
    assert localidades == {"TANTI", "EL DURAZNO"}


@pytest.mark.asyncio
async def test_sync_ignora_filas_en_blanco(db_session: AsyncSession):
    with _mock_sheet([MATRIZ_HEADERS, ROW_OBRA_BLANK, ROW_OBRA_GAS], [ACCIONES_HEADERS]):
        result = await gas_pit_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1


@pytest.mark.asyncio
async def test_sync_repetido_actualiza_no_duplica(db_session: AsyncSession):
    with _mock_sheet([MATRIZ_HEADERS, ROW_OBRA_GAS], [ACCIONES_HEADERS]):
        r1 = await gas_pit_sync.sync_from_sheet(db_session)
        r2 = await gas_pit_sync.sync_from_sheet(db_session)

    assert r1.filas_insertadas == 1
    assert r2.filas_insertadas == 0
    assert r2.filas_actualizadas == 1

    obras = (await db_session.execute(select(GasPitObra))).scalars().all()
    assert len(obras) == 1


# ── ACCIONES TERRITORIO ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_inserta_accion_territorio_y_calcula_usd(db_session: AsyncSession):
    with _mock_sheet([MATRIZ_HEADERS], [ACCIONES_HEADERS, ROW_ACCION_CUMPLIDA]):
        result = await gas_pit_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1
    assert result.filas_insertadas == 1

    accion = (await db_session.execute(select(GasPitAccionTerritorio))).scalar_one()
    assert accion.estado == "Cumplido"
    assert accion.monto_inversion_solicitado == 1000000
    assert float(accion.monto_inversion_usd) == pytest.approx(1000000 * 1460.0)
    assert accion.alerta_localidad == "OK"


@pytest.mark.asyncio
async def test_sync_ignora_fila_sin_localidad_ni_accion(db_session: AsyncSession):
    with _mock_sheet([MATRIZ_HEADERS], [ACCIONES_HEADERS, ROW_ACCION_SIN_LOCALIDAD_NI_ACCION]):
        result = await gas_pit_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 0


# ── Log de sincronización combinado ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_registra_log_con_contadores_combinados(db_session: AsyncSession):
    with _mock_sheet(
        [MATRIZ_HEADERS, ROW_OBRA_GAS],
        [ACCIONES_HEADERS, ROW_ACCION_CUMPLIDA],
    ):
        await gas_pit_sync.sync_from_sheet(db_session, triggered_by="cloud-scheduler")

    log = (await db_session.execute(select(GasPitSyncLog))).scalar_one()
    assert log.filas_leidas == 2
    assert log.filas_insertadas == 2
    assert log.filas_error == 0
    assert log.triggered_by == "cloud-scheduler"
    assert log.finished_at is not None


def _row(nombre_obra: str) -> list:
    row = list(ROW_OBRA_GAS)
    row[3] = nombre_obra
    return row


@pytest.mark.asyncio
async def test_error_de_fila_no_envenena_las_filas_siguientes(db_session: AsyncSession):
    """Aislamiento por SAVEPOINT desde el día uno (lección de
    spec-sync-cc-checklist-tecnico.md §13.5): un error real de DB en la fila del
    medio de un batch no debe frenar el resto ni impedir el log final."""
    real_upsert = gas_pit_sync._upsert_obra
    calls = {"n": 0}

    async def fake_upsert(db, sheet_row_number, r):
        calls["n"] += 1
        if calls["n"] == 2:
            now = datetime.now(timezone.utc)
            db.add(GasPitObra(
                id="dup-a", nombre_obra="Dup A", nombre_obra_norm="dup", departamento_norm="",
                sheet_row_number=999, last_synced_at=now,
            ))
            db.add(GasPitObra(
                id="dup-a", nombre_obra="Dup B", nombre_obra_norm="dup2", departamento_norm="",
                sheet_row_number=998, last_synced_at=now,
            ))
            await db.flush()  # IntegrityError real: primary key duplicada
            return True
        return await real_upsert(db, sheet_row_number, r)

    rows = [
        MATRIZ_HEADERS,
        _row("Obra Uno"), _row("Obra Dos"), _row("Obra Tres"),
    ]
    with _mock_sheet(rows, [ACCIONES_HEADERS]), patch(
        "app.gas_pit.sync._upsert_obra", new=AsyncMock(side_effect=fake_upsert)
    ):
        result = await gas_pit_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 3
    assert result.filas_error == 1
    assert result.filas_insertadas == 2

    log = (await db_session.execute(select(GasPitSyncLog))).scalar_one()
    assert log.filas_insertadas == 2
    assert log.finished_at is not None


@pytest.mark.asyncio
async def test_sync_falla_total_queda_logueada_y_relanza(db_session: AsyncSession):
    with patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(side_effect=RuntimeError("API deshabilitada")),
    ):
        with pytest.raises(gas_pit_sync.SheetReadError):
            await gas_pit_sync.sync_from_sheet(db_session, triggered_by="cloud-scheduler")

    log = (await db_session.execute(select(GasPitSyncLog))).scalar_one()
    assert log.filas_error == 1
    assert log.filas_leidas == 0
    assert "API deshabilitada" in log.errores
    assert log.triggered_by == "cloud-scheduler"
