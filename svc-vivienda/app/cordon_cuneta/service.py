from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.cordon_cuneta.schemas import KpisCordonCuneta, MunicipioResponse, MunicipioUpdate
from app.cordon_cuneta.seed_data import MUNICIPIOS_SEED


async def listar_municipios(db: AsyncSession) -> list[MunicipioResponse]:
    result = await db.execute(
        select(MunicipioCordonCuneta).order_by(MunicipioCordonCuneta.municipio)
    )
    return [MunicipioResponse.model_validate(m) for m in result.scalars().all()]


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
    updates = data.model_dump(exclude_none=True)
    updates["updated_by"] = actor.email
    for key, value in updates.items():
        setattr(municipio, key, value)
    await db.flush()
    await db.refresh(municipio)
    await log_audit(db, actor=actor, action="UPDATE", resource_type="cordon_cuneta", resource_id=municipio_id, payload=updates)
    return MunicipioResponse.model_validate(municipio)


async def get_kpis(db: AsyncSession) -> KpisCordonCuneta:
    result = await db.execute(select(MunicipioCordonCuneta))
    municipios = result.scalars().all()
    total = len(municipios)
    con_ok = sum(1 for m in municipios if m.ok_ministerio)
    monto_total = sum(m.monto or 0 for m in municipios)
    ml_total = sum(m.cordon_cuneta_ml or 0 for m in municipios)
    m2_total = sum(m.adoquinado_m2 or 0 for m in municipios)
    por_estado: dict[str, int] = {}
    for m in municipios:
        estado = m.est_documentacion or "Sin estado"
        por_estado[estado] = por_estado.get(estado, 0) + 1
    return KpisCordonCuneta(
        total_municipios=total,
        con_ok_ministerio=con_ok,
        monto_total=monto_total,
        cordon_cuneta_ml_total=ml_total,
        adoquinado_m2_total=m2_total,
        por_estado_documentacion=por_estado,
    )


async def seed_municipios(db: AsyncSession) -> None:
    """Inserta los 46 municipios iniciales si la tabla está vacía."""
    result = await db.execute(select(func.count(MunicipioCordonCuneta.id)))
    count = result.scalar_one()
    if count > 0:
        return
    for data in MUNICIPIOS_SEED:
        municipio = MunicipioCordonCuneta(**data)
        db.add(municipio)
    await db.flush()
