"""Tests del endpoint interno IAM-only /internal/sync/atp-compromiso-gobernador."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.test_atp_sync import HEADERS_BD, ROW_COMPROMISO_GOBIERNO

SYNC_URL = "/internal/sync/atp-compromiso-gobernador"
ESTADO_URL = "/internal/sync/atp-compromiso-gobernador/estado"


def _mock_sheet(rows):
    return patch(
        "app.integrations.google_sheets.get_values",
        new=AsyncMock(return_value=rows),
    )


@pytest.mark.asyncio
async def test_sync_endpoint_no_requiere_jwt_y_devuelve_resumen(client: AsyncClient):
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_GOBIERNO]):
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
    with _mock_sheet([HEADERS_BD, ROW_COMPROMISO_GOBIERNO]):
        await client.post(SYNC_URL, params={"triggered_by": "cloud-scheduler"})

    r = await client.get(ESTADO_URL)
    assert r.status_code == 200
    data = r.json()
    assert data["filas_insertadas"] == 1
    assert data["triggered_by"] == "cloud-scheduler"
    assert data["finished_at"] is not None
