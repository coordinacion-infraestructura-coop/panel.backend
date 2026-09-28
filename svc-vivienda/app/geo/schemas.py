from typing import Literal

from pydantic import BaseModel


class ResolverItem(BaseModel):
    departamento: str | None = None
    localidad: str | None = None


class ResolverRequest(BaseModel):
    items: list[ResolverItem]


class ResolverResultado(BaseModel):
    departamento_in: str | None
    localidad_in: str | None
    id_geo: str | None
    departamento_oficial: str | None
    localidad_oficial: str | None
    match_tipo: Literal["manual", "exacto", "alias", "sin_match"]


class ResolverResponse(BaseModel):
    resultados: list[ResolverResultado]


class DuplicadoVariante(BaseModel):
    texto: str
    cantidad_filas: int


class DuplicadoGrupo(BaseModel):
    normalizado: str
    variantes: list[DuplicadoVariante]


class DuplicadosResponse(BaseModel):
    grupos: list[DuplicadoGrupo]
