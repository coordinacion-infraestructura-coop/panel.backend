from datetime import date, datetime

from pydantic import BaseModel


class LocalidadFiltro(BaseModel):
    id_geo: str | None
    codigo_indec: str
    nombre: str
    departamento: str
    tipo: str | None  # "Municipio" | "Comuna"


class FuenteFrescura(BaseModel):
    fuente: str
    etiqueta: str
    estado: str  # "ok" | "parcial" | "fallido" | "sin_datos"
    ultima_corrida: datetime | None
    ultimo_periodo: date | None = None
    detalle: str | None = None


class TableroMetaResponse(BaseModel):
    localidades: list[LocalidadFiltro]
    anios: list[int]
    frescura: list[FuenteFrescura]


class InicioKpis(BaseModel):
    localidades: int
    municipios: int
    comunas: int
    poblacion: int
    transferido: float
    por_habitante: float | None


class InicioDepartamento(BaseModel):
    departamento: str
    localidades: int
    poblacion: int
    transferido: float
    por_habitante: float | None


class InicioResponse(BaseModel):
    anio: int
    periodo_hasta: date | None  # último mes con transferencias publicadas en el año
    kpis: InicioKpis
    por_departamento: list[InicioDepartamento]


class ConceptoMonto(BaseModel):
    concepto: str
    etiqueta: str
    monto: float


class TransferenciasResponse(BaseModel):
    concepto: str
    etiqueta: str
    anio: int
    ultimo_periodo: date | None
    total_anio: float
    acumulado_anterior: float | None  # año anterior, de enero al mismo mes
    variacion: float | None
    ultimo_mes: float | None
    mensual: list[float | None]
    mensual_anterior: list[float | None]
    por_concepto: list[ConceptoMonto]
    localidades: int
