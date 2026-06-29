from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.asignaciones import repository
from app.asignaciones.schemas import AsignacionCreate, AsignacionResponse, AsignacionUpdate
from app.audit import log_audit
from app.auth import AuthUser
from app.expedientes import repository as exp_repo
from app.expedientes.models import EstadoExpediente
from app.pubsub import publish_event


async def listar_asignaciones(db: AsyncSession, limit: int = 20, offset: int = 0) -> list[AsignacionResponse]:
    asignaciones = await repository.get_all(db, limit=limit, offset=offset)
    return [AsignacionResponse.model_validate(a) for a in asignaciones]


async def crear_asignacion(
    db: AsyncSession, data: AsignacionCreate, actor: AuthUser
) -> AsignacionResponse:
    expediente = await exp_repo.get_by_id(db, data.expediente_id)
    if not expediente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Expediente {data.expediente_id} no encontrado"},
        )
    if expediente.estado != EstadoExpediente.ASIGNADO.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CONFLICTO_ESTADO",
                "message": f"Solo se puede asignar un expediente en estado ASIGNADO. Estado actual: {expediente.estado}",
            },
        )
    existing = await repository.get_by_expediente(db, data.expediente_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICTO_ESTADO", "message": "El expediente ya tiene una asignación registrada"},
        )
    asignacion = await repository.create(db, {**data.model_dump(), "created_by": actor.email})
    await log_audit(db, actor=actor, action="CREATE", resource_type="asignacion", resource_id=asignacion.id)
    publish_event("vivienda.asignacion.creada", {"id": asignacion.id, "expediente_id": data.expediente_id}, actor.uid, actor.role)
    return AsignacionResponse.model_validate(asignacion)


async def actualizar_asignacion(
    db: AsyncSession, asignacion_id: str, data: AsignacionUpdate, actor: AuthUser
) -> AsignacionResponse:
    a = await repository.get_by_id(db, asignacion_id)
    if not a:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Asignación {asignacion_id} no encontrada"},
        )
    a = await repository.update(db, a, data.model_dump(exclude_none=True))
    await log_audit(db, actor=actor, action="UPDATE", resource_type="asignacion", resource_id=asignacion_id)
    return AsignacionResponse.model_validate(a)
