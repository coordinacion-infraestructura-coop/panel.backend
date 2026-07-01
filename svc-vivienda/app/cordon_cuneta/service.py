from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.cordon_cuneta.models import ConfigCordonCuneta, EstadoCordonCuneta, MunicipioCordonCuneta
from app.cordon_cuneta.schemas import (
    CordonCunetaFullResponse,
    EstadoResponse,
    MunicipioResponse,
    MunicipioUpdate,
    PresupuestoUpdate,
)
from app.cordon_cuneta.seed_data import ESTADOS_SEED, MUNICIPIOS_SEED


async def get_full(db: AsyncSession) -> CordonCunetaFullResponse:
    municipios_res = await db.execute(
        select(MunicipioCordonCuneta).order_by(MunicipioCordonCuneta.orden)
    )
    estados_res = await db.execute(
        select(EstadoCordonCuneta).order_by(EstadoCordonCuneta.orden)
    )
    config_res = await db.execute(select(ConfigCordonCuneta).where(ConfigCordonCuneta.id == 1))
    config = config_res.scalar_one_or_none()
    presupuesto = float(config.presupuesto) if config else 0.0

    return CordonCunetaFullResponse(
        municipios=[MunicipioResponse.model_validate(m) for m in municipios_res.scalars().all()],
        estados=[EstadoResponse.model_validate(e) for e in estados_res.scalars().all()],
        presupuesto=presupuesto,
    )


async def listar_estados(db: AsyncSession) -> list[EstadoResponse]:
    result = await db.execute(select(EstadoCordonCuneta).order_by(EstadoCordonCuneta.orden))
    return [EstadoResponse.model_validate(e) for e in result.scalars().all()]


async def actualizar_municipio(
    db: AsyncSession, municipio_id: str, data: MunicipioUpdate, actor: AuthUser
) -> MunicipioResponse:
    result = await db.execute(
        select(MunicipioCordonCuneta).where(MunicipioCordonCuneta.id == municipio_id)
    )
    municipio = result.scalar_one_or_none()
    if not municipio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Municipio {municipio_id} no encontrado"},
        )
    updates = data.model_dump(exclude_unset=True)
    updates["updated_by"] = actor.email
    for key, value in updates.items():
        setattr(municipio, key, value)
    await db.flush()
    await db.refresh(municipio)
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordon_cuneta",
        resource_id=municipio_id, payload=updates
    )
    return MunicipioResponse.model_validate(municipio)


async def actualizar_presupuesto(
    db: AsyncSession, data: PresupuestoUpdate, actor: AuthUser
) -> float:
    result = await db.execute(select(ConfigCordonCuneta).where(ConfigCordonCuneta.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = ConfigCordonCuneta(id=1, presupuesto=data.presupuesto)
        db.add(config)
    else:
        config.presupuesto = data.presupuesto
    await db.flush()
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordon_cuneta_config",
        resource_id="presupuesto", payload={"presupuesto": data.presupuesto}
    )
    return float(config.presupuesto)


async def seed_cordon_cuneta(db: AsyncSession) -> None:
    count = (await db.execute(select(func.count(MunicipioCordonCuneta.id)))).scalar_one()
    if count > 0:
        return

    for e in ESTADOS_SEED:
        db.add(EstadoCordonCuneta(**e))
    await db.flush()

    for m in MUNICIPIOS_SEED:
        db.add(MunicipioCordonCuneta(**m))
    await db.flush()

    config = ConfigCordonCuneta(id=1, presupuesto=0)
    db.add(config)
    await db.flush()
