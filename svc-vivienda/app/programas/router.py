from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, ROLES_LECTURA, require_roles
from app.database import get_db
from app.programas import service
from app.programas.schemas import ProgramaEstadisticas, ProgramaResponse
from app.programas.tablero import TableroViviendaResponse, get_tablero_vivienda

router = APIRouter()

# Constante LOCAL a este router — no se agrega "TecnicoDGV" a app.auth.ROLES_LECTURA porque
# esa constante la comparten cordon_cuneta/cordoba_hogar/mi_lugar, y ese rol solo debe ver el
# Tablero (este router) + Checklist Técnico, nunca los 3 paneles completos (ver
# docs/files/spec-checklist-tecnico-dgv.md §8).
ROLES_LECTURA_TABLERO = ROLES_LECTURA + ("TecnicoDGV",)


@router.get("/programas", response_model=list[ProgramaResponse])
async def listar_programas(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA_TABLERO)),
):
    """Catálogo de programas habitacionales activos."""
    return await service.listar_programas(db)


@router.get("/programas/tablero", response_model=TableroViviendaResponse)
async def tablero_vivienda(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA_TABLERO)),
):
    """KPIs agregados de CC/CH/ML para el Tablero de Programas — sin exponer los
    paneles completos (accesible a TecnicoDGV, spec-checklist-tecnico-dgv.md §8/§9)."""
    return await get_tablero_vivienda(db)


@router.get("/programas/{programa_id}", response_model=ProgramaResponse)
async def get_programa(
    programa_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA_TABLERO)),
):
    return await service.get_programa(db, programa_id)


@router.get("/programas/{programa_id}/estadisticas", response_model=ProgramaEstadisticas)
async def estadisticas_programa(
    programa_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA_TABLERO)),
):
    """Distribución de expedientes por estado para un programa."""
    return await service.get_estadisticas(db, programa_id)
