"""Tests del endpoint interno IAM-only /internal/sync/gasifera-pit."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.test_gas_pit_sync import ACCIONES_HEADERS, MATRIZ_HEADERS, ROW_OBRA_GAS

SYNC_URL = "/internal/sync/gasifera-pit"
ESTADO_URL = "/internal/sync/gasifera-pit/estado"


def _mock_sheet(matriz_rows, acciones_rows):
    async def fake_get_values(spreadsheet_id, range_name):
        return matriz_rows if range_name.startswith("MATRIZ") else acciones_rows

    return patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(side_effect=fake_get_values),
    )


@pytest.mark.asyncio
async def test_sync_endpoint_no_requiere_jwt_y_devuelve_resumen(client: AsyncClient):
    with _mock_sheet([MATRIZ_HEADERS, ROW_OBRA_GAS], [ACCIONES_HEADERS]):
        r = await client.post(SYNC_URL)

    assert r.status_code == 200
    data = r.json()
    assert data["filas_insertadas"] == 1
    assert data["filas_error"] == 0


@pytest.mark.asyncio
async def test_sync_endpoint_devuelve_502_si_falla_lectura(client: AsyncClient):
    with patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(side_effect=RuntimeError("Sheet no compartido")),
    ):
        r = await client.post(SYNC_URL)

    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "SHEET_SYNC_FALLIDO"


@pytest.mark.asyncio
async def test_estado_null_si_nunca_corrio(client: AsyncClient):
    r = await client.get(ESTADO_URL)
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_estado_devuelve_ultima_corrida(client: AsyncClient):
    with _mock_sheet([MATRIZ_HEADERS, ROW_OBRA_GAS], [ACCIONES_HEADERS]):
        await client.post(SYNC_URL, params={"triggered_by": "cloud-scheduler"})

    r = await client.get(ESTADO_URL)
    assert r.status_code == 200
    data = r.json()
    assert data["filas_insertadas"] == 1
    assert data["triggered_by"] == "cloud-scheduler"
    assert data["finished_at"] is not None
