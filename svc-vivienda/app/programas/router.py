from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, get_current_user
from app.database import get_db
from app.programas import service
from app.programas.schemas import ProgramaEstadisticas, ProgramaResponse

router = APIRouter()


@router.get("/programas", response_model=list[ProgramaResponse])
async def listar_programas(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
):
    """Catálogo de programas habitacionales activos."""
    return await service.listar_programas(db)


@router.get("/programas/{programa_id}", response_model=ProgramaResponse)
async def get_programa(
    programa_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
):
    return await service.get_programa(db, programa_id)


@router.get("/programas/{programa_id}/estadisticas", response_model=ProgramaEstadisticas)
async def estadisticas_programa(
    programa_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
):
    """Distribución de expedientes por estado para un programa."""
    return await service.get_estadisticas(db, programa_id)
