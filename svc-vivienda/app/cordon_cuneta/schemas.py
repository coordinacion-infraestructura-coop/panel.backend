from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EstadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    bg: str
    text_color: str
    orden: int


class MunicipioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    orden: int
    municipio: str
    departamento: str | None
    expediente: str | None
    monto: float | None
    ok_gob: str
    doc_exp: str | None
    ejuridico: int | None
    etecnico: int | None
    efinanciero: int | None
    cordon_cuneta_ml: float | None
    adoquinado_m2: float | None
    obs: str | None
    updated_at: datetime
    updated_by: str | None


class MunicipioUpdate(BaseModel):
    municipio: str | None = None
    departamento: str | None = None
    expediente: str | None = None
    monto: float | None = None
    ok_gob: str | None = None
    doc_exp: str | None = None
    ejuridico: int | None = None
    etecnico: int | None = None
    efinanciero: int | None = None
    cordon_cuneta_ml: float | None = None
    adoquinado_m2: float | None = None
    obs: str | None = None


class CordonCunetaFullResponse(BaseModel):
    municipios: list[MunicipioResponse]
    estados: list[EstadoResponse]
    presupuesto: float


class PresupuestoUpdate(BaseModel):
    presupuesto: float


class PedidoCreate(BaseModel):
    descripcion: str
    fecha_pedido: date


class PedidoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    municipio_id: str
    descripcion: str
    fecha_pedido: date
    created_at: datetime
    created_by: str | None
