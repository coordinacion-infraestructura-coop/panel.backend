from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GobSyncFuenteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    fuente: str
    filas_leidas: int
    filas_upsert: int
    filas_error: int
    filas_sin_match: int
    anomalias: list | dict | None
    estado: str
    corrida_en: datetime
    disparado_por: str | None


class GobSyncResultResponse(BaseModel):
    estado: str  # "ok" | "parcial"
    gobiernos_locales: int
    entes: int
    con_id_geo: int
    sin_id_geo: int
    censo_cerrados: int
    fuentes: list[GobSyncFuenteResponse]


class ZonaRuralResponse(BaseModel):
    departamento: str | None
    poblacion_2022: int | None
    poblacion_2010: int | None
