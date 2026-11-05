from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def adjuntar_schema_ag_sqlite(engine: AsyncEngine) -> None:
    """SQLite no tiene schemas: en tests y en dev sin Postgres, `ag` es una base
    adjunta en memoria, así `ag.ag_localidades` funciona igual que en Postgres."""
    if engine.dialect.name != "sqlite":
        return
    base = engine.url.database
    destino = ":memory:" if not base or base == ":memory:" else f"{base}.ag"

    @event.listens_for(engine.sync_engine, "connect")
    def _attach(dbapi_conn, _record):  # pragma: no cover - trivial
        dbapi_conn.execute(f"ATTACH DATABASE '{destino}' AS ag")


def _crear_engine(url: str) -> AsyncEngine:
    kwargs: dict = {"pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=5, max_overflow=5)
    engine = create_async_engine(url, **kwargs)
    adjuntar_schema_ag_sqlite(engine)
    return engine


engine = _crear_engine(settings.database_url)
# Engine del rol `agente_llm` (spec §2.3). Sin URL propia cae en el engine de la app — sólo
# aceptable en dev/tests; `app.main` lo advierte al arrancar en producción.
engine_llm = _crear_engine(settings.llm_database_url) if settings.llm_database_url else engine

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
LlmSessionLocal = async_sessionmaker(engine_llm, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_llm() -> AsyncSession:
    async with LlmSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
