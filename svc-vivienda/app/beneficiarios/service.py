from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.beneficiarios import repository
from app.beneficiarios.schemas import (
    BeneficiarioCreate,
    BeneficiarioResponse,
    BeneficiariosListResponse,
    BeneficiarioUpdate,
)
from app.pubsub import publish_event


async def listar_beneficiarios(
    db: AsyncSession, limit: int = 20, offset: int = 0, q: str | None = None
) -> BeneficiariosListResponse:
    beneficiarios, total = await repository.get_all(db, limit=limit, offset=offset, q=q)
    return BeneficiariosListResponse(
        data=[BeneficiarioResponse.model_validate(b) for b in beneficiarios],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_beneficiario(db: AsyncSession, beneficiario_id: str) -> BeneficiarioResponse:
    b = await repository.get_by_id(db, beneficiario_id)
    if not b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Beneficiario {beneficiario_id} no encontrado"},
        )
    return BeneficiarioResponse.model_validate(b)


async def buscar_por_dni(db: AsyncSession, dni: str) -> BeneficiarioResponse:
    b = await repository.get_by_dni(db, dni)
    if not b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Beneficiario con DNI {dni} no encontrado"},
        )
    return BeneficiarioResponse.model_validate(b)


async def crear_beneficiario(
    db: AsyncSession, data: BeneficiarioCreate, actor: AuthUser
) -> BeneficiarioResponse:
    # Chequeo incluye soft-deleted: la constraint UNIQUE en DB aplica a todos los registros,
    # y un DNI ya usado (aunque esté eliminado) no puede reutilizarse.
    existing = await repository.get_by_dni_any_status(db, data.dni)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "VALIDACION_FALLIDA", "message": f"Ya existe un beneficiario con DNI {data.dni}"},
        )
    beneficiario = await repository.create(
        db, {**data.model_dump(), "created_by": actor.email}
    )
    await log_audit(db, actor=actor, action="CREATE", resource_type="beneficiario", resource_id=beneficiario.id)
    publish_event("vivienda.beneficiario.creado", {"id": beneficiario.id, "dni": beneficiario.dni}, actor.uid, actor.role)
    return BeneficiarioResponse.model_validate(beneficiario)


async def actualizar_beneficiario(
    db: AsyncSession, beneficiario_id: str, data: BeneficiarioUpdate, actor: AuthUser
) -> BeneficiarioResponse:
    b = await repository.get_by_id(db, beneficiario_id)
    if not b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Beneficiario {beneficiario_id} no encontrado"},
        )
    updates = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    updates["updated_by"] = actor.email
    b = await repository.update(db, b, updates)
    await log_audit(db, actor=actor, action="UPDATE", resource_type="beneficiario", resource_id=b.id, payload=updates)
    return BeneficiarioResponse.model_validate(b)


async def eliminar_beneficiario(
    db: AsyncSession, beneficiario_id: str, actor: AuthUser
) -> None:
    b = await repository.get_by_id(db, beneficiario_id)
    if not b:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Beneficiario {beneficiario_id} no encontrado"},
        )
    await repository.soft_delete(db, b)
    await log_audit(db, actor=actor, action="DELETE", resource_type="beneficiario", resource_id=beneficiario_id)
