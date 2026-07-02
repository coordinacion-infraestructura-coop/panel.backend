from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.beneficiarios.models import Beneficiario


async def get_all(
    db: AsyncSession, limit: int = 20, offset: int = 0, q: str | None = None
) -> tuple[list[Beneficiario], int]:
    base_query = select(Beneficiario).where(Beneficiario.deleted_at.is_(None))
    if q:
        base_query = base_query.where(
            Beneficiario.nombre.ilike(f"%{q}%")
            | Beneficiario.apellido.ilike(f"%{q}%")
            | Beneficiario.dni.ilike(f"%{q}%")
        )
    count_q = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    rows = await db.execute(base_query.order_by(Beneficiario.apellido).limit(limit).offset(offset))
    return list(rows.scalars().all()), total


async def get_by_id(db: AsyncSession, beneficiario_id: str) -> Beneficiario | None:
    result = await db.execute(
        select(Beneficiario).where(
            Beneficiario.id == beneficiario_id,
            Beneficiario.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_by_dni(db: AsyncSession, dni: str) -> Beneficiario | None:
    result = await db.execute(
        select(Beneficiario).where(
            Beneficiario.dni == dni,
            Beneficiario.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_by_dni_any_status(db: AsyncSession, dni: str) -> Beneficiario | None:
    """Busca por DNI incluyendo registros eliminados (para chequeo de unicidad)."""
    result = await db.execute(
        select(Beneficiario).where(Beneficiario.dni == dni)
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, data: dict) -> Beneficiario:
    beneficiario = Beneficiario(**data)
    db.add(beneficiario)
    await db.flush()
    await db.refresh(beneficiario)
    return beneficiario


async def update(db: AsyncSession, beneficiario: Beneficiario, data: dict) -> Beneficiario:
    for key, value in data.items():
        if value is not None:
            setattr(beneficiario, key, value)
    await db.flush()
    await db.refresh(beneficiario)
    return beneficiario


async def soft_delete(db: AsyncSession, beneficiario: Beneficiario) -> None:
    beneficiario.deleted_at = datetime.now(timezone.utc)
    await db.flush()
