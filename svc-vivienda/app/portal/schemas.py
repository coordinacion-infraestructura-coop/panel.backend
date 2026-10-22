from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator

# `TecnicoDGV` se reemplazó por el área "checklist" (spec-portal-areas-de-acceso.md, B4).
ROLES_VALIDOS = ("Admin", "Supervisor", "Operador", "Consulta", "Autoridad")
SECRETARIAS_VALIDAS = ("vivienda", "privada", "infraestructura", "territorial", "gasifera", "gralgob", "desarrollo", "supervision")

# Áreas de acceso por secretaría (spec-portal-areas-de-acceso.md §4). Cada una corresponde a
# pantallas y endpoints del código, por eso el catálogo vive acá y no en la base. Una secretaría
# que no figura todavía no tiene áreas: se comporta como antes.
AREAS_POR_SECRETARIA: dict[str, dict[str, str]] = {
    "vivienda": {
        "cc": "Cordón Cuneta",
        "ch": "Córdoba Hogar",
        "ml": "Mi Lugar",
        "checklist": "Checklist Técnico",
    },
}

NivelArea = Literal["lectura", "edicion"]


def _validar_secretarias(v: list[str]) -> list[str]:
    invalidas = [s for s in v if s not in SECRETARIAS_VALIDAS]
    if invalidas:
        raise ValueError(
            f"Secretarías inválidas: {', '.join(invalidas)}. "
            f"Válidas: {', '.join(SECRETARIAS_VALIDAS)}"
        )
    return v


class AreaAcceso(BaseModel):
    secretaria: str
    area: str
    nivel: NivelArea

    model_config = {"from_attributes": True}


class PortalMeResponse(BaseModel):
    email: str
    nombre: str | None
    rol: str
    secretarias: list[str]
    areas: list[AreaAcceso] = []


class PortalUsuarioCreate(BaseModel):
    email: EmailStr
    nombre: str | None = None
    rol: str = "Operador"
    secretarias: list[str] = []
    areas: list[AreaAcceso] = []

    @field_validator("secretarias")
    @classmethod
    def validar_secretarias(cls, v: list[str]) -> list[str]:
        return _validar_secretarias(v)


class PortalUsuarioUpdate(BaseModel):
    nombre: str | None = None
    rol: str | None = None
    secretarias: list[str] | None = None
    areas: list[AreaAcceso] | None = None
    activo: bool | None = None

    @field_validator("secretarias")
    @classmethod
    def validar_secretarias(cls, v: list[str] | None) -> list[str] | None:
        return v if v is None else _validar_secretarias(v)


class PortalUsuarioResponse(BaseModel):
    email: str
    nombre: str | None
    rol: str
    secretarias: list[str]
    areas: list[AreaAcceso] = []
    activo: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AreaCatalogo(BaseModel):
    area: str
    label: str


def areas_invalidas(areas: list[AreaAcceso], secretarias: list[str]) -> list[str]:
    """Mensajes de error de `areas` contra el catálogo y las secretarías asignadas."""
    errores = []
    vistos = set()
    for a in areas:
        if a.secretaria not in secretarias:
            errores.append(f"{a.secretaria}/{a.area}: la secretaría no está asignada")
        elif a.area not in AREAS_POR_SECRETARIA.get(a.secretaria, {}):
            errores.append(f"{a.secretaria}/{a.area}: área inexistente")
        if (a.secretaria, a.area) in vistos:
            errores.append(f"{a.secretaria}/{a.area}: repetida")
        vistos.add((a.secretaria, a.area))
    return errores
