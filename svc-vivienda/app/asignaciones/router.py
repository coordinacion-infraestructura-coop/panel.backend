from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.asignaciones import service
from app.asignaciones.schemas import AsignacionCreate, AsignacionResponse, AsignacionUpdate
from app.auth import AuthUser, require_roles, ROLES_ESCRITURA, ROLES_LECTURA, ROLES_TRANSICION
from app.database import get_db

router = APIRouter()


@router.get("/asignaciones", response_model=list[AsignacionResponse])
async def listar_asignaciones(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_asignaciones(db, limit=limit, offset=offset)


@router.post("/asignaciones", response_model=AsignacionResponse, status_code=201)
async def crear_asignacion(
    data: AsignacionCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    """Crear asignación. El expediente debe estar en estado ASIGNADO."""
    return await service.crear_asignacion(db, data, actor)


@router.patch("/asignaciones/{asignacion_id}", response_model=AsignacionResponse)
async def actualizar_asignacion(
    asignacion_id: str,
    data: AsignacionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    return await service.actualizar_asignacion(db, asignacion_id, data, actor)
