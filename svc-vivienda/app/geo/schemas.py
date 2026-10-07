from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ResolverItem(BaseModel):
    departamento: str | None = None
    localidad: str | None = None
    # Registros de la fuente que comparten este par, para los clientes que
    # deduplican antes de llamar (Privada, datos externos). Sólo informativo.
    cantidad: int | None = None


class ResolverRequest(BaseModel):
    items: list[ResolverItem]
    origen: str | None = None


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


# ── Asignación manual (spec-geo-asignacion-manual-localidades.md) ────────────

class AliasResumen(BaseModel):
    id: str
    texto_original: str
    departamento_normalizado: str
    id_geo: str | None
    localidad_oficial: str | None
    departamento_oficial: str | None
    motivo: str | None
    origen: str | None
    created_at: datetime
    created_by: str | None


class AliasListResponse(BaseModel):
    items: list[AliasResumen]
    total: int


class PendienteOut(BaseModel):
    id: str
    origen: str
    departamento: str | None
    localidad: str
    cantidad: int | None
    primera_vez: datetime
    ultima_vez: datetime
    estado: Literal["pendiente", "resuelta", "descartada"]
    resuelta_at: datetime | None
    resuelta_by: str | None
    alias: AliasResumen | None


class PendientesResponse(BaseModel):
    items: list[PendienteOut]
    total: int


class ResolverPendienteIn(BaseModel):
    # None = "confirmado sin vínculo"
    id_geo: str | None = None
    alcance: Literal["departamento", "global"] = "departamento"
    motivo: str = Field(min_length=3, max_length=500)
    dry_run: bool = False


class RegistroAfectado(BaseModel):
    programa: Literal["cordon_cuneta", "cordoba_hogar", "mi_lugar"]
    id: str
    nombre_actual: str
    departamento_actual: str | None
    nombre_oficial: str | None
    departamento_oficial: str | None


class DuplicadoGenerado(BaseModel):
    programa: Literal["cordon_cuneta", "cordoba_hogar"]
    cantidad: int


class ResolverPendienteOut(BaseModel):
    dry_run: bool
    id_geo: str | None
    localidad_oficial: str | None
    departamento_oficial: str | None
    registros: list[RegistroAfectado]
    duplicados: list[DuplicadoGenerado]
    pendientes_resueltos: int
    # Qué pasó con cada fuente fuera de Vivienda: "aplicado" | "proximo_sync" |
    # "fallo" | "no_aplica"
    propagacion: dict[str, str]
    avisos: list[str]


class DeshacerOut(BaseModel):
    registros_restaurados: int
    registros_omitidos: int
    pendientes_reabiertos: int
    avisos: list[str]
