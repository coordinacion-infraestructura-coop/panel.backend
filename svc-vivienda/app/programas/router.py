from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, ROLES_LECTURA, require_area, require_roles
from app.database import get_db
from app.programas import service
from app.programas.schemas import ProgramaEstadisticas, ProgramaResponse
from app.programas.tablero import TableroViviendaResponse, get_tablero_vivienda

# Visible con cualquier área de Vivienda (spec-portal-areas-de-acceso.md, B3).
router = APIRouter(dependencies=[Depends(require_area(abierto_a_autoridad=True))])



@router.get("/programas", response_model=list[ProgramaResponse])
async def listar_programas(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """Catálogo de programas habitacionales activos."""
    return await service.listar_programas(db)


# Path con guion (no `/programas/tablero`): un literal que colisiona con
# `/programas/{programa_id}` en el mismo nivel de segmentos rompe el ruteo de
# API Gateway / ESPv2 (404). Misma convención que `cordon-cuneta-config`, etc.
@router.get("/programas-tablero", response_model=TableroViviendaResponse)
async def tablero_vivienda(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """KPIs agregados de CC/CH/ML para el Tablero de Programas — sin exponer los
    paneles completos (accesible con cualquier área de Vivienda, spec-portal-areas-de-acceso.md B3)."""
    return await get_tablero_vivienda(db)


@router.get("/programas/{programa_id}", response_model=ProgramaResponse)
async def get_programa(
    programa_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_programa(db, programa_id)


@router.get("/programas/{programa_id}/estadisticas", response_model=ProgramaEstadisticas)
async def estadisticas_programa(
    programa_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    """Distribución de expedientes por estado para un programa."""
    return await service.get_estadisticas(db, programa_id)
