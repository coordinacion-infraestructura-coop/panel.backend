"""Tests del sync del checklist técnico de Cordón Cuneta (Google Sheet 'Base TOTAL')."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordon_cuneta import checklist_sync
from app.cordon_cuneta.checklist_models import ChecklistItemCC, ChecklistTecnicoCC, SyncLogCC
from app.cordon_cuneta.models import MunicipioCordonCuneta

# ── Filas de ejemplo, con los mismos problemas de calidad de datos reales ──────

ROW_MATCH_POR_EXPEDIENTE = [
    "San Joaquín", "Presidente Roque Sáenz Peña", "0423-079116/2026", "1", "C",
    "DANIEL PICCO", "(3385) 43-5407", "email@x.com", "contacto@x.com",
    "30000000", "206", "",
    "A corregir por M/C", "En Evaluaciòn Jurìdico", "A corregir por M/C", "A corregir por M/C",
    "Completo OK", "A corregir por M/C", "A corregir por M/C", "Completo OK", "Sin Presentar ",
    "A corregir por M/C", "A corregir por M/C", "Completo OK", "A corregir por M/C", "Sin Presentar ",
    "A corregir por M/C", "A corregir por M/C", "En Evaluaciòn Jurìdico", "En Evaluaciòn Jurìdico",
    "En Evaluaciòn Jurìdico",
    "En CURSO en DGV", "Comunicación de prueba con el municipio.", "14/04/2026", "Técnica DGV",
]

ROW_MATCH_POR_NOMBRE = [
    "La Población", "San Javier", "", "2", "C", "EDUARDO ROMERO",
]

ROW_SIN_DEPARTAMENTO = ["Deán Funes"]

ROW_SIN_MATCH = [
    "Pueblo Fantasma", "Departamento Inexistente", "PEDIR BETI", "44", "M",
]

ROW_MARKER = ["☝🏻 AGREGAR NUEVAS LOCALIDADES ARRIBA DE ESTA FILA ☝🏻"]

ROW_DESPUES_DEL_MARKER = ["Nunca Debería Sincronizarse", "Depto X"]

ROW_BLANK: list = []


def _fixture_rows(*rows):
    return list(rows)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def municipio_san_joaquin(db_session: AsyncSession) -> str:
    """Municipio existente cuyo expediente calza EXACTO con la fila del Sheet."""
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid, orden=1, municipio="SAN JOAQUIN", departamento="Pdte R. Sáenz Peña",
        expediente="0423-079116/2026",
    ))
    await db_session.flush()
    return mid


@pytest_asyncio.fixture
async def municipio_la_poblacion(db_session: AsyncSession) -> str:
    """Municipio existente sin expediente cargado — debe matchear por nombre normalizado."""
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid, orden=2, municipio="LA POBLACIÓN", departamento="San Javier", expediente=None,
    ))
    await db_session.flush()
    return mid


def _mock_sheet(rows):
    return patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(return_value=rows),
    )


# ── sync_from_sheet: casos básicos ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_inserta_fila_valida(db_session: AsyncSession, municipio_san_joaquin: str):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE)):
        result = await checklist_sync.sync_from_sheet(db_session, triggered_by="manual")

    assert result.filas_leidas == 1
    assert result.filas_insertadas == 1
    assert result.filas_actualizadas == 0
    assert result.filas_error == 0

    row = (await db_session.execute(select(ChecklistTecnicoCC))).scalar_one()
    assert row.localidad == "San Joaquín"
    assert row.municipio_id == municipio_san_joaquin
    assert row.estado_expediente == "En CURSO en DGV"
    assert row.monto_convenio == 30000000
    assert row.reparticion == "Técnica DGV"
    assert row.fecha_radicacion is not None
    assert row.fecha_radicacion.isoformat() == "2026-04-14"

    items = (await db_session.execute(
        select(ChecklistItemCC).where(ChecklistItemCC.checklist_id == row.id)
    )).scalars().all()
    assert len(items) == 19
    # Los valores con espacio final deben quedar normalizados (trim)
    assert all(i.valor == i.valor.strip() for i in items)
    item_1 = next(i for i in items if i.item_num == 1)
    assert item_1.item_label == "Nota Solicitud de Financiamiento"
    assert item_1.valor == "A corregir por M/C"


@pytest.mark.asyncio
async def test_sync_matchea_por_nombre_si_no_hay_expediente(
    db_session: AsyncSession, municipio_la_poblacion: str
):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_NOMBRE)):
        result = await checklist_sync.sync_from_sheet(db_session)

    assert result.filas_insertadas == 1
    row = (await db_session.execute(select(ChecklistTecnicoCC))).scalar_one()
    assert row.municipio_id == municipio_la_poblacion


@pytest.mark.asyncio
async def test_sync_fila_sin_departamento_no_se_sincroniza(db_session: AsyncSession):
    with _mock_sheet(_fixture_rows(ROW_SIN_DEPARTAMENTO)):
        result = await checklist_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1
    assert result.filas_insertadas == 0
    assert result.filas_error == 1
    assert "departamento" in result.errores[0].motivo

    count = (await db_session.execute(select(ChecklistTecnicoCC))).scalars().all()
    assert count == []


@pytest.mark.asyncio
async def test_sync_fila_sin_match_se_sincroniza_con_municipio_id_nulo(db_session: AsyncSession):
    """Decisión 6: filas sin vínculo se sincronizan igual, con municipio_id NULL, sin error."""
    with _mock_sheet(_fixture_rows(ROW_SIN_MATCH)):
        result = await checklist_sync.sync_from_sheet(db_session)

    assert result.filas_insertadas == 1
    assert result.filas_error == 0
    row = (await db_session.execute(select(ChecklistTecnicoCC))).scalar_one()
    assert row.municipio_id is None
    assert row.expediente == "PEDIR BETI"


@pytest.mark.asyncio
async def test_sync_se_detiene_en_el_marcador_de_fin_de_datos(db_session: AsyncSession):
    with _mock_sheet(_fixture_rows(
        ROW_MATCH_POR_NOMBRE, ROW_MARKER, ROW_DESPUES_DEL_MARKER,
    )):
        result = await checklist_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1  # solo la fila antes del marcador
    rows = (await db_session.execute(select(ChecklistTecnicoCC))).scalars().all()
    assert len(rows) == 1
    assert rows[0].localidad == "La Población"


@pytest.mark.asyncio
async def test_sync_ignora_filas_en_blanco(db_session: AsyncSession):
    with _mock_sheet(_fixture_rows(ROW_BLANK, ROW_MATCH_POR_NOMBRE, ROW_BLANK)):
        result = await checklist_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 1


# ── Idempotencia (UPSERT) ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_repetido_actualiza_no_duplica(db_session: AsyncSession, municipio_san_joaquin: str):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE)):
        r1 = await checklist_sync.sync_from_sheet(db_session)
        r2 = await checklist_sync.sync_from_sheet(db_session)

    assert r1.filas_insertadas == 1
    assert r2.filas_insertadas == 0
    assert r2.filas_actualizadas == 1

    rows = (await db_session.execute(select(ChecklistTecnicoCC))).scalars().all()
    assert len(rows) == 1

    items = (await db_session.execute(select(ChecklistItemCC))).scalars().all()
    assert len(items) == 19  # no se duplican los items en la segunda corrida


@pytest.mark.asyncio
async def test_sync_actualiza_valores_cambiados(db_session: AsyncSession, municipio_san_joaquin: str):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE)):
        await checklist_sync.sync_from_sheet(db_session)

    row_modificada = list(ROW_MATCH_POR_EXPEDIENTE)
    row_modificada[31] = "COMPLETO en DGV"  # estado_expediente cambia

    with _mock_sheet(_fixture_rows(row_modificada)):
        await checklist_sync.sync_from_sheet(db_session)

    row = (await db_session.execute(select(ChecklistTecnicoCC))).scalar_one()
    assert row.estado_expediente == "COMPLETO en DGV"


# ── Log de sincronización ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_registra_log_con_contadores(db_session: AsyncSession, municipio_san_joaquin: str):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE, ROW_SIN_DEPARTAMENTO)):
        await checklist_sync.sync_from_sheet(db_session, triggered_by="cloud-scheduler")

    log = (await db_session.execute(select(SyncLogCC))).scalar_one()
    assert log.filas_leidas == 2
    assert log.filas_insertadas == 1
    assert log.filas_error == 1
    assert log.triggered_by == "cloud-scheduler"
    assert log.finished_at is not None
    assert "Deán Funes" in log.errores


# ── Lectura (endpoint del panel) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_obtener_checklist_tecnico_existente(
    db_session: AsyncSession, municipio_san_joaquin: str
):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE)):
        await checklist_sync.sync_from_sheet(db_session)

    result = await checklist_sync.obtener_checklist_tecnico(db_session, municipio_san_joaquin)
    assert result is not None
    assert result.localidad == "San Joaquín"
    assert len(result.items) == 19


@pytest.mark.asyncio
async def test_obtener_checklist_tecnico_sin_vinculo_devuelve_none(db_session: AsyncSession):
    result = await checklist_sync.obtener_checklist_tecnico(db_session, str(uuid.uuid4()))
    assert result is None


# ── Endpoint HTTP de lectura, vía el panel de Cordón Cuneta ────────────────────

@pytest.mark.asyncio
async def test_endpoint_checklist_tecnico_null_si_no_sincronizado(
    client: AsyncClient, municipio_san_joaquin: str
):
    r = await client.get(f"/api/v1/vivienda/cordon-cuneta/{municipio_san_joaquin}/checklist-tecnico")
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_endpoint_checklist_tecnico_devuelve_datos(
    client: AsyncClient, db_session: AsyncSession, municipio_san_joaquin: str
):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE)):
        await checklist_sync.sync_from_sheet(db_session)

    r = await client.get(f"/api/v1/vivienda/cordon-cuneta/{municipio_san_joaquin}/checklist-tecnico")
    assert r.status_code == 200
    data = r.json()
    assert data["localidad"] == "San Joaquín"
    assert len(data["items"]) == 19
