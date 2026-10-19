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
