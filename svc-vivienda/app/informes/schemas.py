from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EstadoConteo(BaseModel):
    estado_id: int | None
    label: str
    bg: str
    text_color: str
    cantidad: int


class DepartamentoCobertura(BaseModel):
    departamento: str
    cantidad: int
    localidades_cubiertas: int
    localidades_totales: int
    pct_cobertura: float


class EvolucionMes(BaseModel):
    mes: str  # "YYYY-MM"
    cantidad_cambios: int


class PuntoInforme(BaseModel):
    id: str
    nombre: str
    departamento: str | None
    lat: float | None
    lon: float | None
    estado_general_id: int | None
    estado_label: str | None
    estado_bg: str | None
    estado_text_color: str | None
    expediente: str | None
    monto: float | None


class InformePayload(BaseModel):
    """Forma genérica del informe — igual para cualquier programa (CC, CH, ...).
    Las métricas específicas de cada programa (ml de cordón cuneta, cantidad de
    casas, etc.) van en `metricas_extra` para no tener que ramificar el schema.
    """

    programa: str
    total_entidades: int
    monto_total: float
    metricas_extra: dict[str, float | int]
    departamentos_cubiertos: int
    por_estado_general: list[EstadoConteo]
    por_departamento: list[DepartamentoCobertura]
    evolucion_temporal: list[EvolucionMes]
    puntos: list[PuntoInforme]


class InformeSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    payload: InformePayload
    computed_at: datetime
    computed_by: str | None
    duracion_ms: int | None
