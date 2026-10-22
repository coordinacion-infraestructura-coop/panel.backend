from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_LECTURA, AuthUser, require_area, require_roles
from app.database import get_db
from app.tablero_analitico import service
from app.tablero_analitico.schemas import PuntoTendencia, TableroAnaliticoResponse


# Visible con cualquier área de Vivienda (spec-portal-areas-de-acceso.md, B3).
router = APIRouter(dependencies=[Depends(require_area(abierto_a_autoridad=True))])


@router.get("/tablero-analitico", response_model=TableroAnaliticoResponse)
async def get_tablero(
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """Expedientes de CC/CH/ML en vivo, con localidad, estados, checklist y avance de obra."""
    return await service.get_tablero(db, actor)


@router.get("/tablero-analitico/tendencias", response_model=list[PuntoTendencia])
async def get_tendencias(
    dias: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """KPIs diarios de Vivienda de los últimos `dias` días (último snapshot de cada día)."""
    return await service.get_tendencias(db, actor, dias)
