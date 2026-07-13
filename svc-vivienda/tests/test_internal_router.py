"""El endpoint interno de sync no requiere JWT de Firebase (se protege con IAM
de Cloud Run) — se prueba con AsyncClient sin overridear get_current_user."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app

from tests.test_cc_checklist_sync import ROW_MATCH_POR_NOMBRE, _fixture_rows, _mock_sheet


@pytest.mark.asyncio
async def test_sync_endpoint_no_requiere_auth_firebase(db_session: AsyncSession):
    """No se overridea get_current_user — el endpoint /internal no depende de él."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with _mock_sheet(_fixture_rows(ROW_MATCH_POR_NOMBRE)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/internal/sync/cordon-cuneta-checklist")
        assert r.status_code == 200
        data = r.json()
        assert data["filas_leidas"] == 1
        assert data["filas_insertadas"] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sync_endpoint_default_triggered_by_scheduler(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch(
            "app.integrations.google_sheets.get_values", new=AsyncMock(return_value=[])
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/internal/sync/cordon-cuneta-checklist")
        assert r.status_code == 200
        assert r.json() == {
            "filas_leidas": 0,
            "filas_insertadas": 0,
            "filas_actualizadas": 0,
            "filas_error": 0,
            "errores": [],
        }
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sync_endpoint_no_esta_bajo_api_v1(db_session: AsyncSession):
    """El path no debe pasar por el prefijo /api/v1 — el Gateway nunca lo enruta a propósito."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch(
            "app.integrations.google_sheets.get_values", new=AsyncMock(return_value=[])
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r_wrong_prefix = await c.post("/api/v1/internal/sync/cordon-cuneta-checklist")
                r_correct = await c.post("/internal/sync/cordon-cuneta-checklist")
        assert r_wrong_prefix.status_code == 404
        assert r_correct.status_code == 200
    finally:
        app.dependency_overrides.clear()
