from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class SyncResultResponse(BaseModel):
    periodo: date
    tipo: str
    filas_procesadas: int
    filas_sin_match: int
    anomalias: list[str]


class SyncStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    periodo: date
    tipo: str
    filas_procesadas: int
    filas_sin_match: int
    anomalias: list | dict | None
    corrida_en: datetime
    disparado_por: str | None
