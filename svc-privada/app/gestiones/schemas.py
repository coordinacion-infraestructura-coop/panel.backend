from datetime import date, datetime

from pydantic import BaseModel, Field

Estado = str  # VARCHAR + CHECK (ADR-009); los 6 valores validos en models.ESTADOS
Urgencia = str


class GestionCreate(BaseModel):
    ministerio_agencia_id: str
    categoria_general_id: str
    detalle: str = Field(min_length=1)
    departamento: str = Field(min_length=1)
    localidad: str = Field(min_length=1)

    direccion: str | None = None
    observaciones: str | None = None
    urgencia: Urgencia | None = "Media"

    tipo_gestion: str | None = None
    canal_origen: str | None = None

    organismo_id: str | None = None
    subtipo_detalle: str | None = None
    costo_estimado: float | None = None
    costo_moneda: str | None = None
    nro_expediente: str | None = None


class GestionUpdate(BaseModel):
    """PATCH /gestiones/{id} — edición de campos sin cambio de estado (nuevo en v1)."""

    ministerio_agencia_id: str | None = None
    categoria_general_id: str | None = None
    detalle: str | None = None
    observaciones: str | None = None
    urgencia: Urgencia | None = None
    direccion: str | None = None
    subtipo_detalle: str | None = None
    organismo_id: str | None = None
    costo_estimado: float | None = None
    costo_moneda: str | None = None
    tipo_gestion: str | None = None
    canal_origen: str | None = None
    departamento: str | None = None
    localidad: str | None = None

    # lock optimista (spec §3.6). Si viene y no coincide -> 409.
    updated_at: datetime | None = None


class CambioEstado(BaseModel):
    nuevo_estado: Estado
    comentario: str | None = None

    nro_expediente: str | None = None
    fecha_ingreso: date | None = None
    departamento: str | None = None
    localidad: str | None = None

    derivado_a: str | None = None
    acciones_implementadas: str | None = None

    # lock optimista (spec §3.6). Opcional para no romper el frontend viejo.
    updated_at: datetime | None = None


class LocalidadInfoUpsert(BaseModel):
    departamento: str = Field(min_length=1)
    localidad: str = Field(min_length=1)
    habitantes: int | None = None
    electores: int | None = None
    intendente_jefe_comunal: str | None = None
    partido_politico: str | None = None
    tipo_localidad: str | None = None
    color_semaforo: str | None = None
