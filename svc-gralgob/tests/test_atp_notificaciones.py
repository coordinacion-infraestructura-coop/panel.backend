"""Notificación a svc-vivienda cuando el sync de ATP detecta un compromiso
NUEVO (ADR-023)."""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp import sync as atp_sync
from app.config import settings

HEADERS_BD = [
    " ", "DEPARTAMENTO", "LOCALIDAD", "Ministerio", "Fecha de anuncio",
    "Nro. Expediente", "Derivado", "Monto", "Destino", "SALDO ATP",
]
ROW = [
    "1", "CALAMUCHITA", "EMBALSE", "Gobierno", "19/09/2026", "",
    False, "150000000", "ADOQUINADO", "0",
]


def _mock_sheet(rows):
    return patch("app.integrations.google_sheets.get_values", new=AsyncMock(return_value=rows))


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
async def test_compromiso_nuevo_notifica_con_localidad_y_fecha(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW]):
        with patch(
            "app.atp.sync.notificaciones_vivienda.notificar_visita_gobernador", new=AsyncMock()
        ) as mock_notif:
            await atp_sync.sync_from_sheet(db_session)

    mock_notif.assert_awaited_once_with(
        localidad="EMBALSE", departamento="CALAMUCHITA", fecha_anuncio=date(2026, 9, 19)
    )


@pytest.mark.asyncio
async def test_compromiso_existente_no_vuelve_a_notificar(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW]):
        with patch(
            "app.atp.sync.notificaciones_vivienda.notificar_visita_gobernador", new=AsyncMock()
        ) as mock_notif:
            await atp_sync.sync_from_sheet(db_session)  # 1ra corrida: nuevo
            await atp_sync.sync_from_sheet(db_session)  # 2da corrida: ya existe

    assert mock_notif.await_count == 1


@pytest.mark.asyncio
async def test_flag_apagado_no_hace_llamada_http(db_session: AsyncSession):
    """Con el flag apagado, `notificar_visita_gobernador` corre de verdad (no se
    mockea) y debe cortar antes de instanciar el cliente HTTP."""
    settings.notificar_fila_nueva_enabled = False
    with _mock_sheet([HEADERS_BD, ROW]):
        with patch("app.integrations.notificaciones_vivienda.httpx.AsyncClient") as mock_client:
            await atp_sync.sync_from_sheet(db_session)

    mock_client.assert_not_called()
