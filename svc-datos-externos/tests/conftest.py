"""Fixtures compartidos. SQLite in-memory + aiosqlite (sin Postgres
requerido) — mismo patrón que svc-vivienda/svc-gasifera.

Los endpoints internos (`app/internal/router.py`) son IAM-only y no declaran
`Depends(get_current_user)`. El Tablero de Gobierno sí (ADR-028): el `client`
queda autenticado como Admin por default y `as_user` cambia el usuario —
mismo patrón que svc-gralgob."""
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio
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

ADMIN_USER = AuthUser(uid="admin-uid", email="admin@test.com", role="Admin", secretarias=[])
AUTORIDAD_USER = AuthUser(uid="aut-uid", email="autoridad@test.com", role="Autoridad", secretarias=["vivienda"])
SUPERVISOR_USER = AuthUser(uid="sup-uid", email="sup@test.com", role="Supervisor", secretarias=["gralgob"])
CONSULTA_USER = AuthUser(uid="cons-uid", email="consulta@test.com", role="Consulta", secretarias=["vivienda"])
INVITADO_USER = AuthUser(uid="inv-uid", email="invitado@test.com", role="invitado", secretarias=[])


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


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: ADMIN_USER
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client_sin_auth_override(db_session: AsyncSession):
    """Sin override de get_current_user: ejercita la validación real del token."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def as_user():
    """Cambia el usuario inyectado en `client`: as_user(CONSULTA_USER)."""

    def _set(user: AuthUser):
        app.dependency_overrides[get_current_user] = lambda: user

    return _set
