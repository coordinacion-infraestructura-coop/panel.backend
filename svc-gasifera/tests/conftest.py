"""Fixtures compartidos. Estrategia: SQLite in-memory + aiosqlite (sin Postgres
requerido) — mismo patrón que svc-vivienda/svc-privada.

Los endpoints internos de /internal/sync/gasifera-pit (Fase 0) son IAM-only y no
declaran Depends(get_current_user) — el `client` de acá queda autenticado como
Admin por default, pero eso no afecta esos tests (la dependencia nunca se evalúa
para paths que no la declaran). Para el panel de solo lectura (spec §12) sí hace
falta — mismo patrón de fixtures que services/svc-privada/tests/conftest.py."""
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

ADMIN_USER = AuthUser(uid="admin-uid", email="admin@test.com", role="Admin", secretarias=["gasifera"])
OPERADOR_USER = AuthUser(
    uid="op-uid", email="operador@test.com", role="Operador", secretarias=["gasifera"]
)
CONSULTA_USER = AuthUser(
    uid="cons-uid", email="consulta@test.com", role="Consulta", secretarias=["gasifera"]
)
SIN_GASIFERA_USER = AuthUser(
    uid="otra-sec-uid", email="otra.sec@test.com", role="Operador", secretarias=["vivienda"]
)
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


@pytest.fixture
def as_user():
    """Cambia el usuario inyectado en `client`: as_user(OPERADOR_USER)."""

    def _set(user: AuthUser):
        app.dependency_overrides[get_current_user] = lambda: user

    return _set


@pytest_asyncio.fixture
async def client_sin_auth_override(db_session: AsyncSession):
    """Cliente sin override de get_current_user — ejercita la validación real
    del JWT (para probar el caso 'sin token -> 401')."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
