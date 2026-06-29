from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.programas.models import Programa


async def get_all(db: AsyncSession) -> list[Programa]:
    result = await db.execute(select(Programa).where(Programa.activo == True))
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, programa_id: str) -> Programa | None:
    result = await db.execute(select(Programa).where(Programa.id == programa_id))
    return result.scalar_one_or_none()


async def get_by_codigo(db: AsyncSession, codigo: str) -> Programa | None:
    result = await db.execute(select(Programa).where(Programa.codigo == codigo))
    return result.scalar_one_or_none()


async def create(db: AsyncSession, data: dict) -> Programa:
    programa = Programa(**data)
    db.add(programa)
    await db.flush()
    await db.refresh(programa)
    return programa
