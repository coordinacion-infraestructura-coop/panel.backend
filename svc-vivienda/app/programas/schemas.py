from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProgramaBase(BaseModel):
    codigo: str
    nombre: str
    descripcion: str | None = None
    activo: bool = True
    requiere_ingreso_max: bool = False
    ingreso_max: float | None = None


class ProgramaCreate(ProgramaBase):
    pass


class ProgramaResponse(ProgramaBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime


class ProgramaEstadisticas(BaseModel):
    programa_id: str
    codigo: str
    nombre: str
    total_expedientes: int
    por_estado: dict[str, int]
