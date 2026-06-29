from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class BeneficiarioBase(BaseModel):
    dni: str
    cuil: str | None = None
    nombre: str
    apellido: str
    fecha_nacimiento: str | None = None
    email: EmailStr | None = None
    telefono: str | None = None
    domicilio_calle: str | None = None
    domicilio_numero: str | None = None
    domicilio_localidad: str | None = None
    domicilio_departamento: str | None = None
    grupo_familiar_count: int | None = None
    ingreso_mensual: float | None = None
    observaciones: str | None = None


class BeneficiarioCreate(BeneficiarioBase):
    pass


class BeneficiarioUpdate(BaseModel):
    cuil: str | None = None
    nombre: str | None = None
    apellido: str | None = None
    fecha_nacimiento: str | None = None
    email: EmailStr | None = None
    telefono: str | None = None
    domicilio_calle: str | None = None
    domicilio_numero: str | None = None
    domicilio_localidad: str | None = None
    domicilio_departamento: str | None = None
    grupo_familiar_count: int | None = None
    ingreso_mensual: float | None = None
    observaciones: str | None = None


class BeneficiarioResponse(BeneficiarioBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None


class BeneficiariosListResponse(BaseModel):
    data: list[BeneficiarioResponse]
    total: int
    limit: int
    offset: int
