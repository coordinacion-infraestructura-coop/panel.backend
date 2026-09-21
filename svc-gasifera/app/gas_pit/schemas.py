from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ObraGasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    spip: str | None
    expediente: str | None
    division: str | None
    nombre_obra: str
    tipo_obra: str | None
    sub_tipo_obra: str
    contratista: str | None
    estado_obra: str | None
    estado_resumen: str | None
    departamento: str | None
    localidades: list[str] = []
    avance: float | None
    repla_inicial: date | None
    fecha_lic: date | None
    vencimiento: date | None
    plazo_vigente_dias: int | None
    plazo_original: int | None
    contrato_base: float | None
    ampliacion: float | None
    enmienda: float | None
    importe_obra_actualizado: float | None
    importe_dolar: float | None
    prioridad: str | None
    categoria: int | None
    region: str | None
    autorizada_2025: str | None
    pit: bool
    last_synced_at: datetime


class ObrasGasListResponse(BaseModel):
    items: list[ObraGasResponse]
    total: int


class AccionTerritorioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fecha: date | None
    departamento: str | None
    localidad: str | None
    ministerio: str | None
    area: str | None
    id_accion: str | None
    accion: str | None
    detalle_accion: str | None
    estado: str
    monto_inversion_solicitado: float | None
    comentarios: str | None
    monto_inversion_usd: float | None
    alerta_localidad: str | None
    last_synced_at: datetime


class AccionesTerritorioListResponse(BaseModel):
    items: list[AccionTerritorioResponse]
    total: int


class SyncErrorDetail(BaseModel):
    fila: int
    hoja: str
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
