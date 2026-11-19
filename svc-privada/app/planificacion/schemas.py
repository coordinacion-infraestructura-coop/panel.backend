"""Schemas de la planificación de programas (spec-privada-planificacion-programas.md §7)."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AREAS = ("vivienda", "gasifera", "gralgob", "privada", "otra")
FUENTES = ("cordon_cuneta", "cordoba_hogar", "mi_lugar", "gas_pit", "atp")
TIPOS_COLUMNA = ("texto", "texto_largo", "numero", "monto", "si_no", "fecha", "lista")

Area = Literal["vivienda", "gasifera", "gralgob", "privada", "otra"]
Fuente = Literal["cordon_cuneta", "cordoba_hogar", "mi_lugar", "gas_pit", "atp"]
TipoColumna = Literal["texto", "texto_largo", "numero", "monto", "si_no", "fecha", "lista"]
_Color = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Programas ---------------------------------------------------------------------------

class ProgramaIn(_Estricto):
    nombre: str = Field(min_length=1, max_length=200)
    area: Area
    fuente: Fuente | None = None
    descripcion: str | None = None
    orden: int = 0
    activo: bool = True


class ProgramaPatch(_Estricto):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    area: Area | None = None
    fuente: Fuente | None = None
    descripcion: str | None = None
    orden: int | None = None
    activo: bool | None = None


class ProgramaOut(BaseModel):
    id: int
    nombre: str
    area: str
    fuente: str | None
    descripcion: str | None
    orden: int
    activo: bool


# --- Estados / prioridades ---------------------------------------------------------------

class EstadoIn(_Estricto):
    nombre: str = Field(min_length=1, max_length=120)
    color_bg: str | None = _Color
    color_texto: str | None = _Color
    orden: int = 0


class EstadoPatch(_Estricto):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    color_bg: str | None = _Color
    color_texto: str | None = _Color
    orden: int | None = None


class EstadoOut(BaseModel):
    id: int
    programa_id: int
    nombre: str
    color_bg: str | None
    color_texto: str | None
    orden: int
    eliminado: bool


class PrioridadIn(EstadoIn):
    codigo: str = Field(min_length=1, max_length=10)
    excluye: bool = False


class PrioridadPatch(EstadoPatch):
    codigo: str | None = Field(default=None, min_length=1, max_length=10)
    excluye: bool | None = None


class PrioridadOut(EstadoOut):
    codigo: str
    excluye: bool


# --- Columnas ----------------------------------------------------------------------------

class ColumnaIn(_Estricto):
    nombre: str = Field(min_length=1, max_length=120)
    tipo: TipoColumna
    opciones: list[str] | None = None
    orden: int = 0
    visible: bool = True


class ColumnaPatch(_Estricto):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    tipo: TipoColumna | None = None
    opciones: list[str] | None = None
    orden: int | None = None
    visible: bool | None = None


class ColumnaOut(BaseModel):
    id: int
    programa_id: int
    clave: str
    nombre: str
    tipo: str
    opciones: list[str] | None
    orden: int
    visible: bool
    eliminado: bool


# --- Planilla ----------------------------------------------------------------------------

class LocalidadPatch(_Estricto):
    """Upsert parcial: sólo se tocan los campos presentes. `updated_at` es el que el cliente
    vio (null si la fila todavía no existía); si no coincide → 409 (lock optimista)."""

    updated_at: datetime | None = None
    prioridad_id: int | None = None
    estado_id: int | None = None
    ok_gobernador: bool | None = None
    valores: dict[str, Any] | None = None


class EnPanel(BaseModel):
    estado: Literal["si", "no", "sin_dato"]
    lineas: list[dict[str, Any]] = []


class LocalidadPlanOut(BaseModel):
    id_geo: str
    departamento: str
    localidad: str
    tipo_localidad: str | None
    habitantes: int | None
    semaforo: str | None
    prioridad_id: int | None
    estado_id: int | None
    ok_gobernador: bool | None
    valores: dict[str, Any]
    updated_at: datetime | None
    cambios: int
    # Columnas calculadas desde otros servicios (Fases 2–3). `None` = todavía sin cruce.
    en_panel: EnPanel | None = None
    convenio: dict[str, Any] | None = None
    ok_gobernador_panel: bool | None = None
    visita_gobernador: dict[str, Any] | None = None
    coparticipacion_anual: dict[str, Any] | None = None


class LocalidadesOut(BaseModel):
    total: int
    items: list[LocalidadPlanOut]
    fuentes: dict[str, str]


class HistorialOut(BaseModel):
    id: int
    campo: str
    valor_anterior: str | None
    valor_nuevo: str | None
    usuario: str | None
    fecha: datetime
