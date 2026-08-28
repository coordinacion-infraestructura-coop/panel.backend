from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ResumenComunicacion(BaseModel):
    fecha: date
    texto: str | None = None
    area: str | None = None
    autor: str | None = None


class ResumenSubestados(BaseModel):
    juridico: str | None = None
    tecnico: str | None = None
    financiero: str | None = None


class PrivadaConteos(BaseModel):
    por_estado: dict[str, int]
    total: int


class ResumenPrograma(BaseModel):
    """Una línea de programa (Vivienda) o de gestión roll-up (Privada) dentro de una localidad."""

    area: str                              # "vivienda" | "privada"  (clave del filtro de visibilidad)
    programa: str                          # vivienda: cordon_cuneta|cordoba_hogar|mi_lugar · privada: "gestiones"
    programa_label: str
    entidad_id: str | None = None          # id CC/CH/ML · None en la línea roll-up de Privada
    detalle: str | None = None             # ML: nombre del proyecto · Privada: breakdown corto de gestiones
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
    expediente: str | None = None
    privada_conteos: PrivadaConteos | None = None


class ResumenLocalidad(BaseModel):
    localidad: str
    departamento: str | None = None
    programas: list[ResumenPrograma]


class ResumenTerritorialPayload(BaseModel):
    """Forma genérica del resumen — agnóstica de la fuente de cada línea.

    Spec: docs/files/spec-resumen-territorial.md §5.2
    """

    generado_para_areas: list[str]
    total_localidades: int
    total_programas: int
    localidades: list[ResumenLocalidad]


class ResumenSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payload: ResumenTerritorialPayload
    computed_at: datetime
    computed_by: str | None = None
    duracion_ms: int | None = None
