from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class EstadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    bg: str
    text_color: str
    orden: int
    aplica_juridico: bool
    aplica_tecnico: bool
    aplica_financiero: bool


class EstadoCreate(BaseModel):
    label: str
    bg: str
    text_color: str
    orden: int
    aplica_juridico: bool = True
    aplica_tecnico: bool = True
    aplica_financiero: bool = True


class EstadoUpdate(BaseModel):
    label: str | None = None
    bg: str | None = None
    text_color: str | None = None
    orden: int | None = None
    aplica_juridico: bool | None = None
    aplica_tecnico: bool | None = None
    aplica_financiero: bool | None = None


class LocalidadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    orden: int
    localidad: str
    departamento: str | None
    fecha_anuncio: date | None
    expediente: str | None
    monto: float | None
    cantidad_casas: int | None
    ok_gob: str
    doc_exp: str | None
    ejuridico: int | None
    etecnico: int | None
    efinanciero: int | None
    estado_general: int | None
    obs: str | None
    updated_at: datetime
    updated_by: str | None


class LocalidadUpdate(BaseModel):
    localidad: str | None = None
    departamento: str | None = None
    fecha_anuncio: date | None = None
    expediente: str | None = None
    monto: float | None = None
    cantidad_casas: int | None = None
    ok_gob: str | None = None
    doc_exp: str | None = None
    ejuridico: int | None = None
    etecnico: int | None = None
    efinanciero: int | None = None
    obs: str | None = None


class LocalidadCreate(BaseModel):
    localidad: str
    departamento: str | None = None
    fecha_anuncio: date | None = None
    expediente: str | None = None
    monto: float | None = None
    cantidad_casas: int | None = None
    ok_gob: str = "SI"
    ejuridico: int | None = None
    etecnico: int | None = None
    efinanciero: int | None = None


class CordobaHogarFullResponse(BaseModel):
    localidades: list[LocalidadResponse]
    estados: list[EstadoResponse]
    presupuesto: float


class PresupuestoUpdate(BaseModel):
    presupuesto: Decimal


class PedidoCreate(BaseModel):
    descripcion: str
    fecha_pedido: date


class PedidoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    localidad_id: str
    descripcion: str
    fecha_pedido: date
    created_at: datetime
    created_by: str | None


class EstadoHistorialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    localidad_id: str
    campo: str
    estado_anterior_id: int | None
    estado_nuevo_id: int
    created_at: datetime
    created_by: str | None


class GeoLocalidadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_geo: str
    departamento: str
    localidad: str
    lat_centro: float | None
    lon_centro: float | None
    activo: bool
