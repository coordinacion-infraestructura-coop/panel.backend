from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


# ─── Estado ───────────────────────────────────────────────────────────────────

class EstadoMLOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    bg: str
    text_color: str
    orden: int
    aplica_juridico: bool
    aplica_tecnico: bool
    aplica_financiero: bool


class EstadoMLCreate(BaseModel):
    label: str
    bg: str
    text_color: str
    orden: int
    aplica_juridico: bool = True
    aplica_tecnico: bool = True
    aplica_financiero: bool = True


class EstadoMLUpdate(BaseModel):
    label: str | None = None
    bg: str | None = None
    text_color: str | None = None
    orden: int | None = None
    aplica_juridico: bool | None = None
    aplica_tecnico: bool | None = None
    aplica_financiero: bool | None = None


# ─── GeoPunto ─────────────────────────────────────────────────────────────────

class GeoPuntoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lat: Decimal
    lng: Decimal
    orden: int


class GeoPuntoIn(BaseModel):
    lat: Decimal
    lng: Decimal


# ─── Proyecto ─────────────────────────────────────────────────────────────────

class ProyectoMLOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo: str
    nombre: str
    localidad_id: str | None
    localidad_nombre: str
    departamento: str | None
    expediente: str | None
    responsable: str | None
    superficie: Decimal | None
    lotes: int | None
    monto: Decimal | None
    valor_fiscal: Decimal | None
    infra_sin_nexos: Decimal | None
    costo_nexos: Decimal | None
    convenio_unc: Decimal | None
    costo_total_infra: Decimal | None
    ok_gob: str
    ejuridico: int | None
    etecnico: int | None
    efinanciero: int | None
    estado_general: int | None
    obs: str | None
    created_at: datetime
    updated_at: datetime
    updated_by: str | None
    geo_puntos: list[GeoPuntoOut] = []


class ProyectoMLCreate(BaseModel):
    tipo: Literal["exp", "muni", "prov"]
    nombre: str
    localidad_id: str | None = None
    localidad_nombre: str
    departamento: str | None = None
    expediente: str | None = None
    responsable: str | None = None
    superficie: Decimal | None = None
    lotes: int | None = None
    monto: Decimal | None = None
    valor_fiscal: Decimal | None = None
    infra_sin_nexos: Decimal | None = None
    costo_nexos: Decimal | None = None
    convenio_unc: Decimal | None = None
    costo_total_infra: Decimal | None = None
    ok_gob: str = "SI"
    ejuridico: int | None = None
    etecnico: int | None = None
    efinanciero: int | None = None
    estado_general: int | None = None
    obs: str | None = None
    geo_puntos: list[GeoPuntoIn] = []


class ProyectoMLUpdate(BaseModel):
    nombre: str | None = None
    localidad_id: str | None = None
    localidad_nombre: str | None = None
    departamento: str | None = None
    expediente: str | None = None
    responsable: str | None = None
    superficie: Decimal | None = None
    lotes: int | None = None
    monto: Decimal | None = None
    valor_fiscal: Decimal | None = None
    infra_sin_nexos: Decimal | None = None
    costo_nexos: Decimal | None = None
    convenio_unc: Decimal | None = None
    costo_total_infra: Decimal | None = None
    ok_gob: str | None = None
    ejuridico: int | None = None
    etecnico: int | None = None
    efinanciero: int | None = None
    estado_general: int | None = None
    obs: str | None = None
    geo_puntos: list[GeoPuntoIn] | None = None
    fecha_cambio: date | None = None  # para backdating del historial


# ─── Historial ────────────────────────────────────────────────────────────────

class EstadoHistorialMLOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    proyecto_id: str
    campo: str
    estado_anterior_id: int | None
    estado_nuevo_id: int
    created_at: datetime
    created_by: str | None


# ─── Pedido ───────────────────────────────────────────────────────────────────

class PedidoMLOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    proyecto_id: str
    descripcion: str
    fecha_pedido: date
    created_at: datetime
    created_by: str | None
    created_by_nombre: str | None
    secretaria: str | None


class PedidoMLCreate(BaseModel):
    descripcion: str
    fecha_pedido: date


# ─── Config ───────────────────────────────────────────────────────────────────

class ConfigMLOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo_cambio: Decimal
    usd_por_lote: Decimal
    lotes_por_ha: Decimal


class ConfigMLUpdate(BaseModel):
    tipo_cambio: Decimal | None = None
    usd_por_lote: Decimal | None = None
    lotes_por_ha: Decimal | None = None
