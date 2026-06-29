from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, get_current_user, require_roles, ROLES_ESCRITURA, ROLES_LECTURA, ROLES_TRANSICION
from app.database import get_db
from app.expedientes import service
from app.expedientes.schemas import (
    ExpedienteCreate,
    ExpedienteResponse,
    ExpedientesListResponse,
    ExpedienteUpdate,
    HistorialItemResponse,
    TransicionRequest,
)

router = APIRouter()


@router.get("/expedientes", response_model=ExpedientesListResponse)
async def listar_expedientes(
    estado: str | None = Query(None),
    programa_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_expedientes(db, limit=limit, offset=offset, estado=estado, programa_id=programa_id)


@router.post("/expedientes", response_model=ExpedienteResponse, status_code=201)
async def crear_expediente(
    data: ExpedienteCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.crear_expediente(db, data, actor)


@router.get("/expedientes/{expediente_id}", response_model=ExpedienteResponse)
async def get_expediente(
    expediente_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_expediente(db, expediente_id)


@router.patch("/expedientes/{expediente_id}", response_model=ExpedienteResponse)
async def actualizar_expediente(
    expediente_id: str,
    data: ExpedienteUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.actualizar_expediente(db, expediente_id, data, actor)


@router.post("/expedientes/{expediente_id}/transicion", response_model=ExpedienteResponse)
async def transicion_expediente(
    expediente_id: str,
    data: TransicionRequest,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    """Cambiar el estado de un expediente. Requiere rol director o superior."""
    return await service.transicion_expediente(db, expediente_id, data, actor)


@router.get("/expedientes/{expediente_id}/historial", response_model=list[HistorialItemResponse])
async def get_historial(
    expediente_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_historial(db, expediente_id)
