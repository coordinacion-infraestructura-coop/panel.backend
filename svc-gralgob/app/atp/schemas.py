from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CompromisoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    departamento: str | None
    localidad: str | None
    ministerio_destino: str | None
    fecha_anuncio: date | None
    nro_expediente: str | None
    derivado: bool
    monto: float | None
    destino: str | None
    saldo_atp: float | None
    # Suma del cronograma de pago ya sincronizado (atp_cronograma_pagos), NO
    # el campo saldo_atp del Sheet (que la propia hoja fuerza a 0 cuando
    # ministerio_destino != "Gobierno" — ver spec §3.2). Mismo signo que
    # trae el Sheet (negativo = pagado). None si no tiene cronograma cargado.
    total_pagado: float | None
    last_synced_at: datetime


class CompromisosListResponse(BaseModel):
    items: list[CompromisoResponse]
    total: int


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
