from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.checklist_tecnico.schemas import HitoObraPanel
from app.estados_dimension import Dimension, DimensionEditable


# ─── Estado ───────────────────────────────────────────────────────────────────

# Área que lleva cada estado del catálogo (spec-vivienda-tablero-analitico §4.4).
AreaResponsable = Literal["juridica", "tecnica", "financiera", "externa"]

class EstadoMLOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    bg: str
    text_color: str
    orden: int
    tipo: str
    dimension: Dimension
    area_responsable: AreaResponsable | None = None


class EstadoMLCreate(BaseModel):
    label: str
    bg: str
    text_color: str
    orden: int
    tipo: str = "exp"
    dimension: DimensionEditable
    area_responsable: AreaResponsable | None = None


class EstadoMLUpdate(BaseModel):
    label: str | None = None
    bg: str | None = None
    text_color: str | None = None
    orden: int | None = None
    area_responsable: AreaResponsable | None = None


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


# ─── Valuación IDECOR (spec-mi-lugar-valor-fiscal-idecor.md §5.5) ────────────

MAX_NOMENCLATURAS = 50


def normalizar_nomenclaturas(valores: list[str] | None) -> list[str] | None:
    """Solo dígitos, sin vacías ni repetidas, en el orden en que llegaron."""
    if valores is None:
        return None
    limpias = [re.sub(r"\D", "", v or "") for v in valores]
    for v in limpias:
        if len(v) > 30:
            raise ValueError(f"nomenclatura demasiado larga: {v}")
    return list(dict.fromkeys(v for v in limpias if v))


class ParcelaIdecorOut(BaseModel):
    nomenclatura: str
    origen: Literal["punto", "nomenclatura", "ambos"]
    nro_cuenta: str | None = None
    tipo_parcela: str | None = None
    estado: str | None = None
    desig_oficial: str | None = None
    localidad: str | None = None
    superficie_urbana_m2: Decimal = Decimal("0")
    superficie_rural_m2: Decimal = Decimal("0")
    valuacion: Decimal = Decimal("0")
    valuacion_tierra: Decimal = Decimal("0")
    valuacion_mejoras: Decimal = Decimal("0")
    vigencia_desde: date | None = None
    valor_mercado: Decimal | None = None
    vut_pesos_m2: Decimal | None = None
    vur_pesos_ha: Decimal | None = None


class ValuacionIdecorOut(BaseModel):
    """Referencia de IDECOR. `valor_total` es la sugerencia para `valor_fiscal`
    (que sigue siendo manual); `valor_mercado` es solo informativo."""

    estado: Literal["ok", "parcial", "sin_datos", "sin_parcelas", "error"]
    valor_total: Decimal | None = None
    valor_tierra: Decimal | None = None
    valor_mejoras: Decimal | None = None
    valor_mercado: Decimal | None = None
    mercado_anio: int | None = None
    mercado_parcelas_sin_valor: int = 0
    cant_parcelas: int = 0
    puntos_sin_parcela: int = 0
    nomenclaturas_no_encontradas: list[str] = []
    vigencia_desde: date | None = None
    parcelas: list[ParcelaIdecorOut] = []
    consultado_at: datetime | None = None
    ultimo_error_at: datetime | None = None


# ─── Proyecto ─────────────────────────────────────────────────────────────────

class ProyectoMLOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo: str
    nombre: str
    localidad_id: str | None
    localidad_match_tipo: str | None = None
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
    # Avance de obra — solo lectura, viene del Checklist Técnico (spec-checklist-tecnico-dgv v1.6.0 §6-bis)
    avance_obra_pct: int | None = None
    avance_obra_fecha: date | None = None
    fecha_fin_obra: date | None = None
    hitos_obra: list[HitoObraPanel] | None = None
    # Documentación del checklist sin los "No Aplica" (spec-vivienda-tablero-analitico §4.5)
    doc_completos: int | None = None
    doc_total: int | None = None
    doc_iniciado: bool = False
    nomenclaturas: list[str] = []
    valuacion_idecor: ValuacionIdecorOut | None = None


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
    efinanciero: int | None = None
    estado_general: int | None = None
    obs: str | None = None
    geo_puntos: list[GeoPuntoIn] = []
    nomenclaturas: list[str] = Field(default_factory=list, max_length=MAX_NOMENCLATURAS)

    _norm_nomenclaturas = field_validator("nomenclaturas")(normalizar_nomenclaturas)


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
    efinanciero: int | None = None
    estado_general: int | None = None
    obs: str | None = None
    geo_puntos: list[GeoPuntoIn] | None = None
    nomenclaturas: list[str] | None = Field(default=None, max_length=MAX_NOMENCLATURAS)
    fecha_cambio: date | None = None  # para backdating del historial

    _norm_nomenclaturas = field_validator("nomenclaturas")(normalizar_nomenclaturas)


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
    editado_at: datetime | None = None
    editado_por: str | None = None
    editado_por_nombre: str | None = None


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
    monto_por_lote_muni: Decimal


class ConfigMLUpdate(BaseModel):
    tipo_cambio: Decimal | None = None
    usd_por_lote: Decimal | None = None
    lotes_por_ha: Decimal | None = None
    monto_por_lote_muni: Decimal | None = None
