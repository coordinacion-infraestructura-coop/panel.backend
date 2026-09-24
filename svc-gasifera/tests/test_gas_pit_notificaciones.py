"""Notificación a svc-vivienda cuando el sync de gas_pit detecta una acción
territorial NUEVA (ADR-023)."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gas_pit import sync as gas_pit_sync

MATRIZ_HEADERS = ["NOMBRE DE OBRA", "SUB-TIPO DE OBRA", "DEPARTAMENTO", "LOCALIDAD"]

ACCIONES_HEADERS = [
    "Fecha", "Departamento", "Localidad", "Ministerio", "Área", "",
    "ID_ACCION", "Acción", "Detalle de la acción", "Estado",
    "Monto Inversión solicitado", "Comentarios", "Monto Inversión USD",
    "ALERTA_LOCALIDAD", "DEPTO_SUGERIDO",
]
ROW_ACCION = [
    "01/03/2026", "Juárez Celman", "Huanchilla", "Cooperativas y mutuales",
    "Secretaría Gas", "", "A-1", "Red de gas", "Segunda etapa red de gas",
    "Cumplido", "1000000", "Inaugurado", "", "OK", "",
]


def _mock_sheet(matriz_rows, acciones_rows):
    async def fake_get_values(spreadsheet_id, range_name):
        return matriz_rows if range_name.startswith("MATRIZ") else acciones_rows

    return patch("app.integrations.google_sheets.get_values", new=AsyncMock(side_effect=fake_get_values))


@pytest.fixture(autouse=True)
def _flag_on():
    prev_enabled = settings.notificar_fila_nueva_enabled
    prev_url = settings.svc_vivienda_internal_url
    settings.notificar_fila_nueva_enabled = True
    settings.svc_vivienda_internal_url = "https://svc-vivienda.example"
    yield
    settings.notificar_fila_nueva_enabled = prev_enabled
    settings.svc_vivienda_internal_url = prev_url


@pytest.mark.asyncio
async def test_accion_nueva_notifica_con_localidad_y_accion(db_session: AsyncSession):
    with _mock_sheet([MATRIZ_HEADERS], [ACCIONES_HEADERS, ROW_ACCION]):
        with patch(
            "app.gas_pit.sync.notificaciones_vivienda.notificar_accion_nueva", new=AsyncMock()
        ) as mock_notif:
            await gas_pit_sync.sync_from_sheet(db_session)

    mock_notif.assert_awaited_once_with(
        localidad="Huanchilla", departamento="Juárez Celman", accion="Red de gas"
    )


@pytest.mark.asyncio
async def test_accion_existente_no_vuelve_a_notificar(db_session: AsyncSession):
    with _mock_sheet([MATRIZ_HEADERS], [ACCIONES_HEADERS, ROW_ACCION]):
        with patch(
            "app.gas_pit.sync.notificaciones_vivienda.notificar_accion_nueva", new=AsyncMock()
        ) as mock_notif:
            await gas_pit_sync.sync_from_sheet(db_session)  # 1ra: nueva
            await gas_pit_sync.sync_from_sheet(db_session)  # 2da: ya existe (mismo sheet_row_number)

    assert mock_notif.await_count == 1


@pytest.mark.asyncio
async def test_obra_nueva_no_notifica_solo_acciones_territorio(db_session: AsyncSession):
    """Sólo ACCIONES TERRITORIO tiene el campo "acción" pedido — una obra nueva
    en MATRIZ no debe disparar esta alerta."""
    row_obra = [
        "PROVISION DE GAS VIRTUAL A HUANCHILLA", "E- OBRAS DE GAS", "JUAREZ CELMAN", "HUANCHILLA",
    ]
    with _mock_sheet([MATRIZ_HEADERS, row_obra], [ACCIONES_HEADERS]):
        with patch(
            "app.gas_pit.sync.notificaciones_vivienda.notificar_accion_nueva", new=AsyncMock()
        ) as mock_notif:
            await gas_pit_sync.sync_from_sheet(db_session)

    mock_notif.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_apagado_no_hace_llamada_http(db_session: AsyncSession):
    settings.notificar_fila_nueva_enabled = False
    with _mock_sheet([MATRIZ_HEADERS], [ACCIONES_HEADERS, ROW_ACCION]):
        with patch("app.integrations.notificaciones_vivienda.httpx.AsyncClient") as mock_client:
            await gas_pit_sync.sync_from_sheet(db_session)

    mock_client.assert_not_called()
