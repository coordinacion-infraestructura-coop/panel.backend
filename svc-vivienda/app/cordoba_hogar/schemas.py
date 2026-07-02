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
