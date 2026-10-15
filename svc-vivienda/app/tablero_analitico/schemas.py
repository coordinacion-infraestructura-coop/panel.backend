"""Tablero analítico de Vivienda. Spec: docs/files/spec-vivienda-tablero-analitico.md §4."""
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.checklist_tecnico.schemas import HitoObraPanel
from app.resumen_territorial.schemas import ResumenComunicacion, ResumenSubestados


class ExpedienteTablero(BaseModel):
    """Un expediente de CC/CH/ML con su localidad ya resuelta contra el padrón."""

    programa: str                              # cordon_cuneta | cordoba_hogar | mi_lugar
    programa_label: str
    entidad_id: str
    detalle: str | None = None                 # ML: nombre del proyecto
    expediente: str | None = None
    localidad: str
    departamento: str | None = None
    id_geo: str | None = None
    lat: float | None = None                   # centroide del padrón; None sin vínculo
    lon: float | None = None
    estado_general_id: int | None = None
    estado_general_label: str | None = None
    estado_general_bg: str | None = None
    estado_general_text_color: str | None = None
    subestados: ResumenSubestados | None = None
    checklist_total: int = 0
    checklist_faltan: int = 0
    checklist_iniciado: bool = False
    checklist_faltantes: list[str] = Field(default_factory=list)
    ultima_comunicacion: ResumenComunicacion | None = None
    monto: float | None = None
    avance_obra_pct: int | None = None
    avance_obra_fecha: date | None = None
    fecha_fin_obra: date | None = None
    hitos_obra: list[HitoObraPanel] | None = None


class TableroAnaliticoResponse(BaseModel):
    generado_en: datetime
    # Denominador de "X de N localidades": gobiernos locales por departamento, del último
    # snapshot del Resumen Territorial (§4.2); el padrón activo si no hay snapshot.
    total_localidades_padron: int
    total_localidades_por_departamento: dict[str, int]
    expedientes: list[ExpedienteTablero]


class PuntoTendencia(BaseModel):
    fecha: date
    kpis: dict[str, Any]
