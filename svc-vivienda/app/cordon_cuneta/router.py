from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, require_roles, ROLES_ESCRITURA, ROLES_LECTURA
from app.cordon_cuneta import service
from app.cordon_cuneta.schemas import KpisCordonCuneta, MunicipioResponse, MunicipioUpdate
from app.database import get_db

router = APIRouter()


@router.get("/cordon-cuneta", response_model=list[MunicipioResponse])
async def listar_municipios(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """Listado de los 46 municipios del Programa Cordón Cuneta con sus estados."""
    return await service.listar_municipios(db)


@router.get("/cordon-cuneta/kpis", response_model=KpisCordonCuneta)
async def kpis_cordon_cuneta(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """KPIs agregados del programa: montos, metros lineales, estados."""
    return await service.get_kpis(db)


@router.patch("/cordon-cuneta/{municipio_id}", response_model=MunicipioResponse)
async def actualizar_municipio(
    municipio_id: str,
    data: MunicipioUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    """Actualizar estado de un municipio en Cordón Cuneta."""
    return await service.actualizar_municipio(db, municipio_id, data, actor)
