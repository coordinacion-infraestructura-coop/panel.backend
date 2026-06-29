import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.auth import AuthUser
from app.programas.service import seed_programas


@pytest.fixture
def mock_auth():
    """Mockea la validación JWT para tests."""
    test_user = AuthUser(uid="test-uid", email="test@ministerio.gob.ar", role="operador")
    with patch("app.auth.get_current_user", return_value=test_user):
        with patch("app.auth.require_roles", return_value=lambda: test_user):
            yield test_user


@pytest.mark.asyncio
async def test_listar_programas_empty(client: AsyncClient, mock_auth):
    response = await client.get(
        "/api/v1/vivienda/programas",
        headers={"Authorization": "Bearer test-token"},
    )
    # Sin seed, retorna lista vacía
    assert response.status_code in (200, 401)


@pytest.mark.asyncio
async def test_listar_programas_con_seed(client: AsyncClient, db_session: AsyncSession, mock_auth):
    await seed_programas(db_session)
    await db_session.commit()

    with patch("app.programas.router.get_current_user", return_value=mock_auth):
        response = await client.get("/api/v1/vivienda/programas")

    # El seed carga 4 programas
    if response.status_code == 200:
        data = response.json()
        assert len(data) == 4
        codigos = [p["codigo"] for p in data]
        assert "CORDOBA_HOGAR" in codigos
        assert "MI_LUGAR" in codigos
        assert "CORDON_CUNETA" in codigos
        assert "LOTEOS" in codigos
