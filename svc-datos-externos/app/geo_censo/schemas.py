from pydantic import BaseModel, ConfigDict


class GeoCensoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_geo: str | None
    codigo_indec: str
    categoria: str
    departamento_censo: str | None
    localidad_censo: str
    poblacion_2022: int | None
    viviendas_2022: int | None
