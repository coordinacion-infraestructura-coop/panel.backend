from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.estados_dimension import Dimension, DimensionEditable

from app.checklist_tecnico.schemas import HitoObraPanel


# Área que lleva cada estado del catálogo (spec-vivienda-tablero-analitico §4.4).
AreaResponsable = Literal["juridica", "tecnica", "financiera", "externa"]

class EstadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    bg: str
    text_color: str
    orden: int
    dimension: Dimension
    area_responsable: AreaResponsable | None = None


class EstadoCreate(BaseModel):
    label: str
    bg: str
    text_color: str
    orden: int
    dimension: DimensionEditable
    area_responsable: AreaResponsable | None = None


class EstadoUpdate(BaseModel):
    label: str | None = None
    bg: str | None = None
    text_color: str | None = None
    orden: int | None = None
    area_responsable: AreaResponsable | None = None


class MunicipioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    orden: int
    municipio: str
    departamento: str | None
    localidad_id: str | None = None
    localidad_match_tipo: str | None = None
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
    # Avance de obra — solo lectura, viene del Checklist Técnico (spec-checklist-tecnico-dgv v1.6.0 §6-bis)
    avance_obra_pct: int | None = None
    avance_obra_fecha: date | None = None
    fecha_fin_obra: date | None = None
    hitos_obra: list[HitoObraPanel] | None = None
    # Documentación del checklist sin los "No Aplica" (spec-vivienda-tablero-analitico §4.5)
    doc_completos: int | None = None
    doc_total: int | None = None
    doc_iniciado: bool = False


class MunicipioUpdate(BaseModel):
    municipio: str | None = None
    departamento: str | None = None
    expediente: str | None = None
    monto: float | None = None
    ok_gob: str | None = None
    doc_exp: str | None = None
    ejuridico: int | None = None
    efinanciero: int | None = None
    estado_general: int | None = None
    cordon_cuneta_ml: float | None = None
    adoquinado_m2: float | None = None
    obs: str | None = None
    fecha_cambio: date | None = None


class MunicipioCreate(BaseModel):
    municipio: str
    departamento: str | None = None
    expediente: str | None = None
    monto: float | None = None
    ok_gob: str = "SI"
    ejuridico: int | None = None
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
    created_by_nombre: str | None
    secretaria: str | None
    editado_at: datetime | None = None
    editado_por: str | None = None
    editado_por_nombre: str | None = None


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
