from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.expedientes.models import EstadoExpediente


class ExpedienteCreate(BaseModel):
    beneficiario_id: str
    programa_id: str
    observaciones: str | None = None
    prioridad: int = 0


class ExpedienteUpdate(BaseModel):
    observaciones: str | None = None
    prioridad: int | None = None


class TransicionRequest(BaseModel):
    estado_nuevo: EstadoExpediente
    observacion: str | None = None


class HistorialItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    estado_anterior: str | None
    estado_nuevo: str
    observacion: str | None
    actor_uid: str
    actor_rol: str
    created_at: datetime


class ExpedienteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    numero_expediente: str
    beneficiario_id: str
    programa_id: str
    estado: str
    fecha_solicitud: datetime
    fecha_resolucion: datetime | None
    observaciones: str | None
    prioridad: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None


class ExpedientesListResponse(BaseModel):
    data: list[ExpedienteResponse]
    total: int
    limit: int
    offset: int
