from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.cordoba_hogar.models import (
    ConfigCordobaHogar,
    EstadoCordobaHogar,
    LocalidadCordobaHogar,
    PedidoCordobaHogar,
)
from app.cordoba_hogar.schemas import (
    CordobaHogarFullResponse,
    EstadoResponse,
    LocalidadResponse,
    LocalidadUpdate,
    PedidoCreate,
    PedidoResponse,
    PresupuestoUpdate,
)
from app.cordoba_hogar.seed_data import ESTADOS_SEED, LOCALIDADES_SEED


async def get_full(db: AsyncSession) -> CordobaHogarFullResponse:
    localidades_res = await db.execute(
        select(LocalidadCordobaHogar).order_by(LocalidadCordobaHogar.orden)
    )
    estados_res = await db.execute(
        select(EstadoCordobaHogar).order_by(EstadoCordobaHogar.orden)
    )
    config_res = await db.execute(select(ConfigCordobaHogar).where(ConfigCordobaHogar.id == 1))
    config = config_res.scalar_one_or_none()
    presupuesto = float(config.presupuesto) if config else 0.0

    return CordobaHogarFullResponse(
        localidades=[LocalidadResponse.model_validate(l) for l in localidades_res.scalars().all()],
        estados=[EstadoResponse.model_validate(e) for e in estados_res.scalars().all()],
        presupuesto=presupuesto,
    )


async def listar_estados(db: AsyncSession) -> list[EstadoResponse]:
    result = await db.execute(select(EstadoCordobaHogar).order_by(EstadoCordobaHogar.orden))
    return [EstadoResponse.model_validate(e) for e in result.scalars().all()]


async def actualizar_localidad(
    db: AsyncSession, localidad_id: str, data: LocalidadUpdate, actor: AuthUser
) -> LocalidadResponse:
    result = await db.execute(
        select(LocalidadCordobaHogar).where(LocalidadCordobaHogar.id == localidad_id)
    )
    localidad = result.scalar_one_or_none()
    if not localidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Localidad {localidad_id} no encontrada"},
        )
    updates = data.model_dump(exclude_unset=True)
    updates["updated_by"] = actor.email
    for key, value in updates.items():
        setattr(localidad, key, value)
    await db.flush()
    await db.refresh(localidad)
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordoba_hogar",
        resource_id=localidad_id, payload=updates
    )
    return LocalidadResponse.model_validate(localidad)


async def actualizar_presupuesto(
    db: AsyncSession, data: PresupuestoUpdate, actor: AuthUser
) -> float:
    result = await db.execute(select(ConfigCordobaHogar).where(ConfigCordobaHogar.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = ConfigCordobaHogar(id=1, presupuesto=data.presupuesto)
        db.add(config)
    else:
        config.presupuesto = data.presupuesto
    await db.flush()
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordoba_hogar_config",
        resource_id="presupuesto", payload={"presupuesto": str(data.presupuesto)}
    )
    return float(config.presupuesto)


async def listar_pedidos(db: AsyncSession, localidad_id: str) -> list[PedidoResponse]:
    result = await db.execute(
        select(PedidoCordobaHogar)
        .where(PedidoCordobaHogar.localidad_id == localidad_id)
        .order_by(PedidoCordobaHogar.fecha_pedido.desc())
    )
    return [PedidoResponse.model_validate(p) for p in result.scalars().all()]


async def crear_pedido(
    db: AsyncSession, localidad_id: str, data: PedidoCreate, actor: AuthUser
) -> PedidoResponse:
    localidad = (await db.execute(
        select(LocalidadCordobaHogar).where(LocalidadCordobaHogar.id == localidad_id)
    )).scalar_one_or_none()
    if not localidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Localidad {localidad_id} no encontrada"},
        )
    pedido = PedidoCordobaHogar(
        localidad_id=localidad_id,
        descripcion=data.descripcion,
        fecha_pedido=data.fecha_pedido,
        created_by=actor.email,
    )
    db.add(pedido)
    await db.flush()
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="ch_pedido",
        resource_id=pedido.id, payload={"localidad_id": localidad_id, "fecha_pedido": str(data.fecha_pedido)}
    )
    return PedidoResponse.model_validate(pedido)


async def delete_pedido(
    db: AsyncSession, localidad_id: str, pedido_id: str, actor: AuthUser
) -> None:
    result = await db.execute(
        select(PedidoCordobaHogar).where(
            PedidoCordobaHogar.id == pedido_id,
            PedidoCordobaHogar.localidad_id == localidad_id,
        )
    )
    pedido = result.scalar_one_or_none()
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": "Pedido no encontrado"},
        )
    await db.delete(pedido)
    await log_audit(
        db, actor=actor, action="DELETE", resource_type="ch_pedido",
        resource_id=pedido_id, payload={"localidad_id": localidad_id}
    )


async def seed_cordoba_hogar(db: AsyncSession) -> None:
    count = (await db.execute(select(func.count(LocalidadCordobaHogar.id)))).scalar_one()
    if count > 0:
        return

    for e in ESTADOS_SEED:
        db.add(EstadoCordobaHogar(**e))
    await db.flush()

    for loc in LOCALIDADES_SEED:
        db.add(LocalidadCordobaHogar(**loc))
    await db.flush()

    config = ConfigCordobaHogar(id=1, presupuesto=0)
    db.add(config)
    await db.flush()
