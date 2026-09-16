from decimal import Decimal

from pydantic import BaseModel


class LocalidadInformeRow(BaseModel):
    departamento: str
    localidad: str
    cant_habitantes: int | None = None
    tiene_cordon_cuneta: bool
    ml_cordon_cuneta: Decimal | None = None
    tiene_viviendas: bool
    cantidad_viviendas: int | None = None
