from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.asignaciones.models import TipoBien


class AsignacionCreate(BaseModel):
    expediente_id: str
    tipo_bien: TipoBien
    identificador_bien: str
    domicilio_bien: str | None = None
    fecha_escritura: datetime | None = None
    observaciones: str | None = None


class AsignacionUpdate(BaseModel):
    domicilio_bien: str | None = None
    fecha_escritura: datetime | None = None
    observaciones: str | None = None


class AsignacionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    expediente_id: str
    tipo_bien: str
    identificador_bien: str
    domicilio_bien: str | None
    fecha_escritura: datetime | None
    observaciones: str | None
    created_at: datetime
    created_by: str | None
