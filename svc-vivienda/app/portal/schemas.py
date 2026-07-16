from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, field_validator

ROLES_VALIDOS = ("Admin", "Supervisor", "Operador", "Consulta")
SECRETARIAS_VALIDAS = ("vivienda", "privada", "infraestructura", "territorial", "gasifera", "desarrollo", "supervision")


class PortalMeResponse(BaseModel):
    email: str
    nombre: str | None
    rol: str
    secretarias: list[str]


class PortalUsuarioCreate(BaseModel):
    email: EmailStr
    nombre: str | None = None
    rol: str = "Operador"
    secretarias: list[str] = []

    @field_validator("secretarias")
    @classmethod
    def validar_secretarias(cls, v: list[str]) -> list[str]:
        invalidas = [s for s in v if s not in SECRETARIAS_VALIDAS]
        if invalidas:
            raise ValueError(
                f"Secretarías inválidas: {', '.join(invalidas)}. "
                f"Válidas: {', '.join(SECRETARIAS_VALIDAS)}"
            )
        return v


class PortalUsuarioUpdate(BaseModel):
    nombre: str | None = None
    rol: str | None = None
    secretarias: list[str] | None = None
    activo: bool | None = None

    @field_validator("secretarias")
    @classmethod
    def validar_secretarias(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        invalidas = [s for s in v if s not in SECRETARIAS_VALIDAS]
        if invalidas:
            raise ValueError(
                f"Secretarías inválidas: {', '.join(invalidas)}. "
                f"Válidas: {', '.join(SECRETARIAS_VALIDAS)}"
            )
        return v


class PortalUsuarioResponse(BaseModel):
    email: str
    nombre: str | None
    rol: str
    secretarias: list[str]
    activo: bool
    created_at: datetime

    model_config = {"from_attributes": True}
