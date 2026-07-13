from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ChecklistItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_num: int
    item_label: str
    valor: str


class ChecklistTecnicoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    localidad: str
    departamento: str | None
    expediente: str | None
    tipo: str | None
    intendente: str | None
    telefono: str | None
    email: str | None
    contacto_tecnico: str | None
    monto_convenio: float | None
    cordon_cuneta_ml: float | None
    adoquinado_m2: float | None
    estado_expediente: str | None
    observaciones: str | None
    fecha_radicacion: date | None
    reparticion: str | None
    last_synced_at: datetime
    items: list[ChecklistItemResponse]


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
