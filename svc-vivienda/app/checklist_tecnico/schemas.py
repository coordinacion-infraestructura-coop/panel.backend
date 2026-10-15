from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.checklist_tecnico.catalog import Programa, TipoHito


class CatalogoEstadoExpedienteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    orden: int
    activo: bool
    en_ruta: bool


class CatalogoEstadoExpedienteCreate(BaseModel):
    label: str
    orden: int
    activo: bool = True
    en_ruta: bool = True


class CatalogoEstadoExpedienteUpdate(BaseModel):
    label: str | None = None
    orden: int | None = None
    activo: bool | None = None
    en_ruta: bool | None = None


class CatalogoReparticionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    programa: Programa | None
    label: str
    orden: int
    activo: bool


class CatalogoReparticionCreate(BaseModel):
    programa: Programa | None = None
    label: str
    orden: int
    activo: bool = True


class CatalogoReparticionUpdate(BaseModel):
    programa: Programa | None = None
    label: str | None = None
    orden: int | None = None
    activo: bool | None = None


class CatalogoItemEstadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    orden: int
    activo: bool
    bg: str
    text_color: str
    es_completo: bool
    excluye_completitud: bool


class CatalogoItemEstadoCreate(BaseModel):
    label: str
    orden: int
    activo: bool = True
    bg: str = "#f1f5f9"
    text_color: str = "#64748b"
    es_completo: bool = False
    excluye_completitud: bool = False

    @model_validator(mode="after")
    def _flags_excluyentes(self) -> "CatalogoItemEstadoCreate":
        if self.es_completo and self.excluye_completitud:
            raise ValueError("Un estado no puede ser 'completo' y 'no aplica' a la vez")
        return self


class CatalogoItemEstadoUpdate(BaseModel):
    label: str | None = None
    orden: int | None = None
    activo: bool | None = None
    bg: str | None = None
    text_color: str | None = None
    es_completo: bool | None = None
    excluye_completitud: bool | None = None


class ItemSubDefinicion(BaseModel):
    sub_item_num: int
    label: str


class ItemDefinicion(BaseModel):
    item_num: int
    label: str
    sub_items: list[ItemSubDefinicion] | None


class CatalogosResponse(BaseModel):
    estados_expediente: list[CatalogoEstadoExpedienteResponse]
    reparticiones: list[CatalogoReparticionResponse]
    items_estado: list[CatalogoItemEstadoResponse]
    items_por_programa: dict[str, list[ItemDefinicion]]


class EntidadResumen(BaseModel):
    """Datos de convenio, de solo lectura acá — se editan en el panel general del programa (spec §3)."""
    nombre: str
    departamento: str | None
    expediente: str | None
    monto: float | None
    dato_extra_label: str | None = None
    dato_extra_valor: str | None = None


class EntidadListItem(BaseModel):
    """Fila mínima del selector de localidad/programa (spec §6, enmienda 1.1.0).

    Reemplaza el uso de los GET de panel completo de cordon_cuneta/cordoba_hogar/mi_lugar,
    que están vedados a TecnicoDGV — el único rol que usa esta pantalla.
    """
    programa: Programa
    id: str
    nombre: str
    departamento: str | None
    # Resuelto contra viv_geo_localidades (ADR-024) — permite al frontend agrupar
    # la misma localidad real entre CC/CH/ML aunque el texto crudo difiera.
    id_geo: str | None = None


class ChecklistPedidoCreate(BaseModel):
    descripcion: str
    fecha_pedido: date


class ChecklistPedidoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    descripcion: str
    fecha_pedido: date
    created_at: datetime
    created_by: str | None = None
    created_by_nombre: str | None = None
    secretaria: str | None = None


class ObraObsCreate(BaseModel):
    descripcion: str
    fecha: date


class ObraObsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    descripcion: str
    fecha: date
    created_at: datetime
    created_by: str | None = None
    created_by_nombre: str | None = None


class ChecklistItemResponse(BaseModel):
    item_num: int
    sub_item_num: int | None
    label: str
    item_estado_id: int
    item_estado_label: str
    bg: str
    text_color: str


class ChecklistItemUpdate(BaseModel):
    item_estado_id: int
    sub_item_num: int | None = None


class HitoResponse(BaseModel):
    tipo: TipoHito
    label: str
    monto: float | None
    fecha_acreditado: date | None
    # Derivada del historial de avance (spec v1.6.0 §5.6) — siempre None en 'anticipo'.
    fecha_medicion: date | None = None


class AvanceVigente(BaseModel):
    porcentaje: int
    fecha_medicion: date


class AvanceMedicionCreate(BaseModel):
    fecha_medicion: date
    porcentaje: int = Field(ge=0, le=100)

    @field_validator("fecha_medicion")
    @classmethod
    def _no_futura(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("La fecha de medición no puede ser futura")
        return v


class AvanceMedicionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fecha_medicion: date
    porcentaje: int
    created_at: datetime
    created_by: str | None = None
    created_by_nombre: str | None = None


class HitoObraPanel(BaseModel):
    """Hito de obra tal como lo ven los paneles CC/CH/ML — solo lectura (spec v1.6.0 §6-bis)."""
    tipo: TipoHito
    monto: float | None
    fecha_medicion: date | None
    fecha_acreditado: date | None


class HitoUpdate(BaseModel):
    fecha_acreditado: date | None = None


class ChecklistTecnicoResponse(BaseModel):
    programa: Programa
    entidad_id: str
    entidad: EntidadResumen
    estado_expediente_id: int | None
    estado_expediente_label: str | None
    fecha_radicacion: date | None
    reparticion_id: int | None
    reparticion_label: str | None
    estados_visitados: list[int]
    items: list[ChecklistItemResponse]
    hitos: list[HitoResponse] | None
    fecha_fin_obra: date | None = None
    avance: AvanceVigente | None = None
    updated_at: datetime
    updated_by: str | None


class ChecklistTecnicoUpdate(BaseModel):
    estado_expediente_id: int | None = None
    fecha_radicacion: date | None = None
    reparticion_id: int | None = None
    fecha_fin_obra: date | None = None
