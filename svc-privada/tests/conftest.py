"""Fixtures compartidos para los tests de svc-privada.

Estrategia (igual que svc-vivienda):
- SQLite in-memory + aiosqlite (sin PostgreSQL requerido)
- get_current_user sobreescrito -> inyecta usuario de prueba
- log_audit parcheado (CAST AS jsonb es PostgreSQL-específico)
"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import AuthUser, get_current_user
from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

ADMIN_USER = AuthUser(uid="admin-uid", email="admin@test.com", role="Admin", secretarias=["privada"])
OPERADOR_USER = AuthUser(
    uid="op-uid", email="operador@test.com", role="Operador", secretarias=["privada"]
)
CONSULTA_USER = AuthUser(
    uid="cons-uid", email="consulta@test.com", role="Consulta", secretarias=["privada"]
)
INVITADO_USER = AuthUser(uid="inv-uid", email="invitado@test.com", role="invitado", secretarias=[])


@pytest_asyncio.fixture
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSession() as session:
        yield session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER

    with patch("app.audit.log_audit", new=AsyncMock(return_value=None)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def as_user():
    """Cambia el usuario inyectado: as_user(OPERADOR_USER)."""

    def _set(user: AuthUser):
        app.dependency_overrides[get_current_user] = lambda: user

    return _set
