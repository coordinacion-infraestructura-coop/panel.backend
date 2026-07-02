from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, get_current_user, require_roles, ROLES_ELIMINACION, ROLES_ESCRITURA, ROLES_LECTURA
from app.database import get_db
from app.beneficiarios import service
from app.beneficiarios.schemas import (
    BeneficiarioCreate,
    BeneficiarioResponse,
    BeneficiariosListResponse,
    BeneficiarioUpdate,
)

router = APIRouter()


@router.get("/beneficiarios", response_model=BeneficiariosListResponse)
async def listar_beneficiarios(
    q: str | None = Query(None, description="Búsqueda por nombre, apellido o DNI"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_beneficiarios(db, limit=limit, offset=offset, q=q)


@router.get("/beneficiarios/buscar", response_model=BeneficiarioResponse)
async def buscar_por_dni(
    dni: str = Query(..., description="DNI a buscar"),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.buscar_por_dni(db, dni)


@router.post("/beneficiarios", response_model=BeneficiarioResponse, status_code=201)
async def crear_beneficiario(
    data: BeneficiarioCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.crear_beneficiario(db, data, actor)


@router.get("/beneficiarios/{beneficiario_id}", response_model=BeneficiarioResponse)
async def get_beneficiario(
    beneficiario_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_beneficiario(db, beneficiario_id)


@router.patch("/beneficiarios/{beneficiario_id}", response_model=BeneficiarioResponse)
async def actualizar_beneficiario(
    beneficiario_id: str,
    data: BeneficiarioUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.actualizar_beneficiario(db, beneficiario_id, data, actor)


@router.delete("/beneficiarios/{beneficiario_id}", status_code=204)
async def eliminar_beneficiario(
    beneficiario_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ELIMINACION)),
):
    await service.eliminar_beneficiario(db, beneficiario_id, actor)
