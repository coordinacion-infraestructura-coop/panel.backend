from datetime import datetime

from pydantic import BaseModel, EmailStr

ROLES_VALIDOS = ("Admin", "Supervisor", "Operador", "Consulta")
SECRETARIAS_VALIDAS = ("vivienda", "privada", "infraestructura", "territorial", "gasifera", "desarrollo")


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


class PortalUsuarioUpdate(BaseModel):
    nombre: str | None = None
    rol: str | None = None
    secretarias: list[str] | None = None
    activo: bool | None = None


class PortalUsuarioResponse(BaseModel):
    email: str
    nombre: str | None
    rol: str
    secretarias: list[str]
    activo: bool
    created_at: datetime

    model_config = {"from_attributes": True}
