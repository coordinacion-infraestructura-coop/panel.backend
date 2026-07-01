from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, require_roles, ROLES_ESCRITURA, ROLES_LECTURA
from app.cordon_cuneta import service
from app.cordon_cuneta.schemas import (
    CordonCunetaFullResponse,
    EstadoResponse,
    MunicipioResponse,
    MunicipioUpdate,
    PresupuestoUpdate,
)
from app.database import get_db

router = APIRouter()


@router.get("/cordon-cuneta", response_model=CordonCunetaFullResponse)
async def get_panel(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """Devuelve los 46 municipios, los estados configurados y el presupuesto asignado."""
    return await service.get_full(db)


@router.get("/cordon-cuneta/estados", response_model=list[EstadoResponse])
async def listar_estados(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_estados(db)


@router.patch("/cordon-cuneta/{municipio_id}", response_model=MunicipioResponse)
async def actualizar_municipio(
    municipio_id: str,
    data: MunicipioUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    """Actualiza el estado de un municipio en Cordón Cuneta."""
    return await service.actualizar_municipio(db, municipio_id, data, actor)


@router.patch("/cordon-cuneta-config/presupuesto", response_model=float)
async def actualizar_presupuesto(
    data: PresupuestoUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    """Actualiza el crédito presupuestario asignado al programa."""
    return await service.actualizar_presupuesto(db, data, actor)
