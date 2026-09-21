from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SyncErrorDetail(BaseModel):
    fila: int
    motivo: str


class SyncResultResponse(BaseModel):
    filas_leidas: int
    filas_insertadas: int
    filas_actualizadas: int
    filas_error: int
    errores: list[SyncErrorDetail]


class SyncStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    started_at: datetime
    finished_at: datetime | None
    filas_leidas: int
    filas_insertadas: int
    filas_actualizadas: int
    filas_error: int
    triggered_by: str | None
