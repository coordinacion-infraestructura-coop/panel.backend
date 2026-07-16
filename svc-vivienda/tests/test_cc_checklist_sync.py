"""Tests del sync del checklist técnico de Cordón Cuneta (Google Sheet 'Base TOTAL')."""
import uuid
from datetime import datetime, timezone
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
async def test_error_de_fila_no_envenena_las_filas_siguientes(db_session: AsyncSession):
    """Regresión del incidente de producción 2026-07-16: un error real de DB al
    escribir una fila (ahí: StringDataRightTruncationError por un valor del
    Sheet más largo que la columna) NO debe dejar la sesión inutilizable para
    el resto del batch ni impedir que se escriba el log final. Se fuerza acá
    un IntegrityError real (PK duplicada) en la fila del medio — mismo efecto
    sobre la sesión de SQLAlchemy que el bug real, portable entre motores."""
    real_upsert_row = checklist_sync._upsert_row
    calls = {"n": 0}

    async def fake_upsert_row(db, sheet_row_number, localidad, departamento, row):
        calls["n"] += 1
        if calls["n"] == 2:
            db.add(ChecklistTecnicoCC(
                id="fila-duplicada", localidad="Dup A", departamento="X",
                sheet_row_number=999, last_synced_at=datetime.now(timezone.utc),
            ))
            db.add(ChecklistTecnicoCC(
                id="fila-duplicada", localidad="Dup B", departamento="Y",
                sheet_row_number=999, last_synced_at=datetime.now(timezone.utc),
            ))
            await db.flush()  # IntegrityError real: primary key duplicada
            return True
        return await real_upsert_row(db, sheet_row_number, localidad, departamento, row)

    rows = _fixture_rows(
        ["Localidad Uno", "Depto A"],
        ["Localidad Dos", "Depto B"],   # esta falla
        ["Localidad Tres", "Depto C"],
    )
    with _mock_sheet(rows), patch(
        "app.cordon_cuneta.checklist_sync._upsert_row", new=AsyncMock(side_effect=fake_upsert_row)
    ):
        result = await checklist_sync.sync_from_sheet(db_session)

    assert result.filas_leidas == 3
    assert result.filas_error == 1
    assert result.filas_insertadas == 2  # Uno y Tres, a pesar del error en Dos

    localidades = {
        r.localidad for r in (await db_session.execute(select(ChecklistTecnicoCC))).scalars().all()
    }
    assert localidades == {"Localidad Uno", "Localidad Tres"}

    # El log final debe haberse escrito igual (antes del fix, esto también fallaba
    # con PendingRollbackError y la corrida entera se perdía sin dejar rastro).
    log = (await db_session.execute(select(SyncLogCC))).scalar_one()
    assert log.filas_insertadas == 2
    assert log.finished_at is not None


@pytest.mark.asyncio
async def test_sync_falla_total_queda_logueada_y_relanza(db_session: AsyncSession):
    """Si falla la lectura del Sheet entero (Sheets API caída, credenciales, etc.),
    debe quedar un registro en viv_cc_sync_log y debe re-lanzar SheetReadError
    (para que el endpoint devuelva un error HTTP real, no un 200 silencioso)."""
    with patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(side_effect=RuntimeError("API deshabilitada")),
    ):
        with pytest.raises(checklist_sync.SheetReadError):
            await checklist_sync.sync_from_sheet(db_session, triggered_by="cloud-scheduler")

    log = (await db_session.execute(select(SyncLogCC))).scalar_one()
    assert log.filas_error == 1
    assert log.filas_leidas == 0
    assert "API deshabilitada" in log.errores
    assert log.triggered_by == "cloud-scheduler"
    assert log.finished_at is not None


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


# ── Estado del último sync + forzar sync (botón "Actualizar ahora" del panel) ──

ESTADO_URL = "/api/v1/vivienda/cordon-cuneta-checklist-tecnico/estado"
SYNC_URL = "/api/v1/vivienda/cordon-cuneta-checklist-tecnico/sync"


@pytest.mark.asyncio
async def test_estado_sync_null_si_nunca_corrio(client: AsyncClient):
    r = await client.get(ESTADO_URL)
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_estado_sync_devuelve_ultima_corrida(
    client: AsyncClient, db_session: AsyncSession, municipio_san_joaquin: str
):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE)):
        await checklist_sync.sync_from_sheet(db_session, triggered_by="cloud-scheduler")

    r = await client.get(ESTADO_URL)
    assert r.status_code == 200
    data = r.json()
    assert data["filas_leidas"] == 1
    assert data["filas_insertadas"] == 1
    assert data["triggered_by"] == "cloud-scheduler"
    assert data["finished_at"] is not None


@pytest.mark.asyncio
async def test_forzar_sync_admin_dispara_y_registra_actor(
    client: AsyncClient, municipio_san_joaquin: str
):
    with _mock_sheet(_fixture_rows(ROW_MATCH_POR_EXPEDIENTE)):
        r = await client.post(SYNC_URL)
    assert r.status_code == 200
    data = r.json()
    assert data["filas_insertadas"] == 1

    estado = (await client.get(ESTADO_URL)).json()
    assert estado["triggered_by"] == "manual-ui:admin@test.com"


@pytest.mark.asyncio
async def test_forzar_sync_operador_permitido(client_operador: AsyncClient):
    with _mock_sheet(_fixture_rows(ROW_SIN_DEPARTAMENTO)):
        r = await client_operador.post(SYNC_URL)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_forzar_sync_denegado_a_consulta(client_consulta: AsyncClient):
    r = await client_consulta.post(SYNC_URL)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_forzar_sync_devuelve_502_si_falla(client: AsyncClient):
    with patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(side_effect=RuntimeError("Sheet no compartido")),
    ):
        r = await client.post(SYNC_URL)
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "SHEET_SYNC_FALLIDO"
