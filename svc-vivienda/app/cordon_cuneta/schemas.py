from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MunicipioUpdate(BaseModel):
    numero_expediente: str | None = None
    monto: float | None = None
    cordon_cuneta_ml: float | None = None
    adoquinado_m2: float | None = None
    est_documentacion: str | None = None
    est_juridico_adm: str | None = None
    est_tecnico: str | None = None
    est_presup_fin: str | None = None
    ok_ministerio: bool | None = None
    observaciones: str | None = None


class MunicipioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    municipio: str
    departamento: str | None
    numero_expediente: str | None
    monto: float | None
    cordon_cuneta_ml: float | None
    adoquinado_m2: float | None
    est_documentacion: str | None
    est_juridico_adm: str | None
    est_tecnico: str | None
    est_presup_fin: str | None
    ok_ministerio: bool
    observaciones: str | None
    updated_at: datetime
    updated_by: str | None


class KpisCordonCuneta(BaseModel):
    total_municipios: int
    con_ok_ministerio: int
    monto_total: float
    cordon_cuneta_ml_total: float
    adoquinado_m2_total: float
    por_estado_documentacion: dict[str, int]
