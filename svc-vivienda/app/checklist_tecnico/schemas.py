from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.checklist_tecnico.catalog import Programa, TipoHito, ValorItem


class CatalogoEstadoExpedienteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    orden: int
    activo: bool


class CatalogoEstadoExpedienteCreate(BaseModel):
    label: str
    orden: int
    activo: bool = True


class CatalogoEstadoExpedienteUpdate(BaseModel):
    label: str | None = None
    orden: int | None = None
    activo: bool | None = None


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
    items_por_programa: dict[str, list[ItemDefinicion]]


class EntidadResumen(BaseModel):
    """Datos de convenio, de solo lectura acá — se editan en el panel general del programa (spec §3)."""
    nombre: str
    departamento: str | None
    expediente: str | None
    monto: float | None
    dato_extra_label: str | None = None
    dato_extra_valor: str | None = None


class ChecklistItemResponse(BaseModel):
    item_num: int
    sub_item_num: int | None
    label: str
    valor: ValorItem


class ChecklistItemUpdate(BaseModel):
    valor: ValorItem
    sub_item_num: int | None = None


class HitoResponse(BaseModel):
    tipo: TipoHito
    label: str
    monto: float | None
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
    items: list[ChecklistItemResponse]
    hitos: list[HitoResponse] | None
    updated_at: datetime
    updated_by: str | None


class ChecklistTecnicoUpdate(BaseModel):
    estado_expediente_id: int | None = None
    fecha_radicacion: date | None = None
    reparticion_id: int | None = None
