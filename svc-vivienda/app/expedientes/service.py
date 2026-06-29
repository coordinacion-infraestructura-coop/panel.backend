from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.expedientes import repository
from app.expedientes.models import EstadoExpediente, TRANSICIONES_VALIDAS
from app.expedientes.schemas import (
    ExpedienteCreate,
    ExpedienteResponse,
    ExpedientesListResponse,
    ExpedienteUpdate,
    HistorialItemResponse,
    TransicionRequest,
)
from app.pubsub import publish_event


async def listar_expedientes(
    db: AsyncSession,
    limit: int = 20,
    offset: int = 0,
    estado: str | None = None,
    programa_id: str | None = None,
) -> ExpedientesListResponse:
    expedientes, total = await repository.get_all(
        db, limit=limit, offset=offset, estado=estado, programa_id=programa_id
    )
    return ExpedientesListResponse(
        data=[ExpedienteResponse.model_validate(e) for e in expedientes],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_expediente(db: AsyncSession, expediente_id: str) -> ExpedienteResponse:
    e = await repository.get_by_id(db, expediente_id)
    if not e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Expediente {expediente_id} no encontrado"},
        )
    return ExpedienteResponse.model_validate(e)


async def crear_expediente(
    db: AsyncSession, data: ExpedienteCreate, actor: AuthUser
) -> ExpedienteResponse:
    hay_activo = await repository.has_expediente_activo_en_programa(
        db, data.beneficiario_id, data.programa_id
    )
    if hay_activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFLICTO_ESTADO",
                "message": "El beneficiario ya tiene un expediente activo en este programa",
            },
        )
    year = datetime.now(timezone.utc).year
    numero = await repository.get_next_numero(db, year)
    expediente = await repository.create(
        db,
        {
            **data.model_dump(),
            "numero_expediente": numero,
            "estado": EstadoExpediente.INGRESADO.value,
            "created_by": actor.email,
        },
    )
    await repository.add_historial(
        db,
        expediente_id=expediente.id,
        estado_anterior=None,
        estado_nuevo=EstadoExpediente.INGRESADO.value,
        observacion="Expediente creado",
        actor_uid=actor.uid,
        actor_rol=actor.role,
    )
    await log_audit(db, actor=actor, action="CREATE", resource_type="expediente", resource_id=expediente.id)
    publish_event("vivienda.expediente.creado", {"id": expediente.id, "numero": numero}, actor.uid, actor.role)
    return ExpedienteResponse.model_validate(expediente)


async def actualizar_expediente(
    db: AsyncSession, expediente_id: str, data: ExpedienteUpdate, actor: AuthUser
) -> ExpedienteResponse:
    e = await repository.get_by_id(db, expediente_id)
    if not e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Expediente {expediente_id} no encontrado"},
        )
    updates = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    updates["updated_by"] = actor.email
    e = await repository.update(db, e, updates)
    await log_audit(db, actor=actor, action="UPDATE", resource_type="expediente", resource_id=expediente_id, payload=updates)
    return ExpedienteResponse.model_validate(e)


async def transicion_expediente(
    db: AsyncSession, expediente_id: str, data: TransicionRequest, actor: AuthUser
) -> ExpedienteResponse:
    e = await repository.get_by_id(db, expediente_id)
    if not e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Expediente {expediente_id} no encontrado"},
        )
    estado_actual = EstadoExpediente(e.estado)
    estados_permitidos = TRANSICIONES_VALIDAS.get(estado_actual, [])
    if data.estado_nuevo not in estados_permitidos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CONFLICTO_ESTADO",
                "message": f"Transición inválida: {estado_actual.value} → {data.estado_nuevo.value}. "
                           f"Permitidas: {[s.value for s in estados_permitidos]}",
            },
        )
    estado_anterior = e.estado
    updates = {
        "estado": data.estado_nuevo.value,
        "updated_by": actor.email,
    }
    if data.estado_nuevo in (EstadoExpediente.APROBADO, EstadoExpediente.RECHAZADO, EstadoExpediente.ASIGNADO):
        updates["fecha_resolucion"] = datetime.now(timezone.utc)
    e = await repository.update(db, e, updates)
    await repository.add_historial(
        db,
        expediente_id=expediente_id,
        estado_anterior=estado_anterior,
        estado_nuevo=data.estado_nuevo.value,
        observacion=data.observacion,
        actor_uid=actor.uid,
        actor_rol=actor.role,
    )
    await log_audit(
        db, actor=actor, action="TRANSICION", resource_type="expediente",
        resource_id=expediente_id,
        payload={"estado_anterior": estado_anterior, "estado_nuevo": data.estado_nuevo.value},
    )
    publish_event(
        "vivienda.expediente.estado_cambiado",
        {"id": expediente_id, "estado_anterior": estado_anterior, "estado_nuevo": data.estado_nuevo.value},
        actor.uid, actor.role,
    )
    return ExpedienteResponse.model_validate(e)


async def get_historial(db: AsyncSession, expediente_id: str) -> list[HistorialItemResponse]:
    e = await repository.get_by_id(db, expediente_id)
    if not e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Expediente {expediente_id} no encontrado"},
        )
    historial = await repository.get_historial(db, expediente_id)
    return [HistorialItemResponse.model_validate(h) for h in historial]
