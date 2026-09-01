"""Auth real de svc-privada (ADR-015): JWT Firebase + lookup portal_usuarios
via endpoint interno de svc-vivienda. Acá NO se overridea get_current_user."""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, get_db
from app.main import app
from tests.conftest import TestSession, test_engine


@pytest_asyncio.fixture
async def raw_client():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSession() as session:
        async def _get_db():
            yield session

        app.dependency_overrides[get_db] = _get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _mock_jwt(email: str):
    """Parchea la validación del JWT para que devuelva un payload fijo."""
    return patch.multiple(
        "app.auth",
        _google_public_keys=lambda: {"keys": [{"kid": "k"}]},
    ), patch("app.auth.jwt.get_unverified_header", return_value={"kid": "k"}), \
       patch("app.auth.jwt.decode", return_value={"sub": "uid-1", "email": email})


@pytest.mark.asyncio
async def test_sin_bearer_401(raw_client):
    r = await raw_client.get("/api/v1/privada/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_usuario_privada_ok(raw_client):
    m1, m2, m3 = _mock_jwt("priv@test.com")
    portal = AsyncMock(return_value={"rol": "Operador", "nombre": "Priv", "secretarias": ["privada"], "activo": True})
    with m1, m2, m3, patch("app.auth._fetch_portal_user", portal):
        r = await raw_client.get("/api/v1/privada/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"email": "priv@test.com", "nombre": "Priv", "rol": "Operador", "modulos": []}


@pytest.mark.asyncio
async def test_usuario_sin_secretaria_privada_403(raw_client):
    m1, m2, m3 = _mock_jwt("otro@test.com")
    portal = AsyncMock(return_value={"rol": "Operador", "nombre": "O", "secretarias": ["vivienda"], "activo": True})
    with m1, m2, m3, patch("app.auth._fetch_portal_user", portal):
        r = await raw_client.get("/api/v1/privada/gestiones", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_lookup_falla_degrada_a_invitado_403(raw_client):
    m1, m2, m3 = _mock_jwt("x@test.com")
    with m1, m2, m3, patch("app.auth._fetch_portal_user", AsyncMock(return_value=None)):
        r = await raw_client.get("/api/v1/privada/gestiones", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403  # rol "invitado" no está en ROLES_LECTURA


@pytest.mark.asyncio
async def test_admin_sin_secretaria_privada_pasa(raw_client):
    m1, m2, m3 = _mock_jwt("admin@test.com")
    portal = AsyncMock(return_value={"rol": "Admin", "nombre": "A", "secretarias": [], "activo": True})
    with m1, m2, m3, patch("app.auth._fetch_portal_user", portal):
        r = await raw_client.get("/api/v1/privada/gestiones", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200  # Admin no requiere la secretaría
