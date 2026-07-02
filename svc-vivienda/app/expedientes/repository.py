from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.expedientes.models import Expediente, HistorialExpediente


async def get_next_numero(db: AsyncSession, year: int) -> str:
    """Genera el próximo número de expediente VIV-YYYY-NNNNNN.

    Usa MAX sobre el número como string (zero-padded a 6 dígitos, por lo que
    el orden alfabético coincide con el numérico). Más robusto que COUNT cuando
    existen registros manuales o gaps en la secuencia.
    Nota: requiere lock de fila externo o manejo de IntegrityError en
    el caller para eliminar la race condition bajo carga concurrente.
    """
    prefix = f"VIV-{year}-"
    result = await db.execute(
        select(func.max(Expediente.numero_expediente)).where(
            Expediente.numero_expediente.like(f"{prefix}%")
        )
    )
    max_num = result.scalar_one_or_none()
    if max_num:
        last_n = int(max_num.split("-")[-1])
        return f"{prefix}{last_n + 1:06d}"
    return f"{prefix}000001"


async def get_all(
    db: AsyncSession,
    limit: int = 20,
    offset: int = 0,
    estado: str | None = None,
    programa_id: str | None = None,
) -> tuple[list[Expediente], int]:
    base_query = select(Expediente).where(Expediente.deleted_at.is_(None))
    if estado:
        base_query = base_query.where(Expediente.estado == estado)
    if programa_id:
        base_query = base_query.where(Expediente.programa_id == programa_id)
    count_q = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_q)).scalar_one()
    rows = await db.execute(
        base_query.order_by(Expediente.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars().all()), total


async def get_by_id(db: AsyncSession, expediente_id: str) -> Expediente | None:
    result = await db.execute(
        select(Expediente)
        .where(Expediente.id == expediente_id, Expediente.deleted_at.is_(None))
        .options(selectinload(Expediente.historial))
    )
    return result.scalar_one_or_none()


async def has_expediente_activo_en_programa(
    db: AsyncSession, beneficiario_id: str, programa_id: str
) -> bool:
    """Un beneficiario no puede tener más de 1 expediente activo por programa."""
    estados_inactivos = ["RECHAZADO", "BAJA"]
    result = await db.execute(
        select(func.count(Expediente.id)).where(
            Expediente.beneficiario_id == beneficiario_id,
            Expediente.programa_id == programa_id,
            Expediente.deleted_at.is_(None),
            ~Expediente.estado.in_(estados_inactivos),
        )
    )
    return result.scalar_one() > 0


async def create(db: AsyncSession, data: dict) -> Expediente:
    expediente = Expediente(**data)
    db.add(expediente)
    await db.flush()
    await db.refresh(expediente)
    return expediente


async def update(db: AsyncSession, expediente: Expediente, data: dict) -> Expediente:
    for key, value in data.items():
        setattr(expediente, key, value)
    await db.flush()
    await db.refresh(expediente)
    return expediente


async def add_historial(
    db: AsyncSession,
    expediente_id: str,
    estado_anterior: str | None,
    estado_nuevo: str,
    observacion: str | None,
    actor_uid: str,
    actor_rol: str,
) -> None:
    item = HistorialExpediente(
        expediente_id=expediente_id,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        observacion=observacion,
        actor_uid=actor_uid,
        actor_rol=actor_rol,
    )
    db.add(item)
    await db.flush()


async def get_historial(db: AsyncSession, expediente_id: str) -> list[HistorialExpediente]:
    result = await db.execute(
        select(HistorialExpediente)
        .where(HistorialExpediente.expediente_id == expediente_id)
        .order_by(HistorialExpediente.created_at.asc())
    )
    return list(result.scalars().all())
