from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.asignaciones.models import Asignacion


async def get_all(db: AsyncSession, limit: int = 20, offset: int = 0) -> list[Asignacion]:
    result = await db.execute(
        select(Asignacion).order_by(Asignacion.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, asignacion_id: str) -> Asignacion | None:
    result = await db.execute(select(Asignacion).where(Asignacion.id == asignacion_id))
    return result.scalar_one_or_none()


async def get_by_expediente(db: AsyncSession, expediente_id: str) -> Asignacion | None:
    result = await db.execute(
        select(Asignacion).where(Asignacion.expediente_id == expediente_id)
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, data: dict) -> Asignacion:
    asignacion = Asignacion(**data)
    db.add(asignacion)
    await db.flush()
    await db.refresh(asignacion)
    return asignacion


async def update(db: AsyncSession, asignacion: Asignacion, data: dict) -> Asignacion:
    for key, value in data.items():
        if value is not None:
            setattr(asignacion, key, value)
    await db.flush()
    await db.refresh(asignacion)
    return asignacion
