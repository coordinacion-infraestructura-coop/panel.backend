from datetime import date, datetime

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
    estado_general: int | None
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
    estado_general: int | None = None
    cordon_cuneta_ml: float | None = None
    adoquinado_m2: float | None = None
    obs: str | None = None


class MunicipioCreate(BaseModel):
    municipio: str
    departamento: str | None = None
    expediente: str | None = None
    monto: float | None = None
    ok_gob: str = "SI"
    ejuridico: int | None = None
    etecnico: int | None = None
    efinanciero: int | None = None


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


class EstadoHistorialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    municipio_id: str
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
