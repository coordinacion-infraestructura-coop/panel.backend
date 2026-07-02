"""
Fixtures compartidos para todos los tests de svc-vivienda.

Estrategia:
- SQLite in-memory + aiosqlite (sin PostgreSQL requerido)
- get_current_user sobreescrito → inyecta usuario de prueba
- log_audit parcheado en cada service (CAST AS jsonb es PostgreSQL-específico)
- pubsub deshabilitado automáticamente (settings.environment == "development")
"""
from contextlib import ExitStack
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
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

# ── Usuarios de prueba ─────────────────────────────────────────────────────────

ADMIN_USER = AuthUser(
    uid="admin-uid",
    email="admin@test.com",
    role="Admin",
    secretarias=["vivienda", "privada"],
)
OPERADOR_USER = AuthUser(
    uid="op-uid",
    email="operador@test.com",
    role="Operador",
    secretarias=["vivienda"],
)
CONSULTA_USER = AuthUser(
    uid="cons-uid",
    email="consulta@test.com",
    role="Consulta",
    secretarias=["vivienda"],
)
INVITADO_USER = AuthUser(
    uid="inv-uid",
    email="invitado@test.com",
    role="invitado",
    secretarias=[],
)

MOCK_TOKEN = "test-token-dev"

# Los módulos que hacen INSERT en viv_audit_log (CAST AS jsonb, solo PostgreSQL)
_AUDIT_PATCH_TARGETS = [
    "app.expedientes.service.log_audit",
    "app.beneficiarios.service.log_audit",
    "app.asignaciones.service.log_audit",
    "app.cordoba_hogar.service.log_audit",
    "app.cordon_cuneta.service.log_audit",
]


# ── Fixtures de base de datos ──────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True, scope="function")
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with TestSession() as session:
        yield session


# ── Clientes HTTP con roles distintos ─────────────────────────────────────────

def _make_client_fixture(user: AuthUser):
    """Genera un fixture de AsyncClient autenticado con el usuario dado."""

    @pytest_asyncio.fixture
    async def _client(db_session: AsyncSession):
        async def override_get_db():
            yield db_session

        async def get_test_user():
            return user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = get_test_user

        with ExitStack() as stack:
            for target in _AUDIT_PATCH_TARGETS:
                stack.enter_context(patch(target, new=AsyncMock()))
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                yield c

        app.dependency_overrides.clear()

    return _client


client = _make_client_fixture(ADMIN_USER)
client_operador = _make_client_fixture(OPERADOR_USER)
client_consulta = _make_client_fixture(CONSULTA_USER)
client_invitado = _make_client_fixture(INVITADO_USER)
