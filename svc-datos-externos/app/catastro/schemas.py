from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_ELEMENTOS = 50


class PuntoIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class ValuacionRequest(BaseModel):
    puntos: list[PuntoIn] = Field(default_factory=list, max_length=MAX_ELEMENTOS)
    nomenclaturas: list[str] = Field(default_factory=list, max_length=MAX_ELEMENTOS)

    @model_validator(mode="after")
    def _al_menos_uno(self) -> "ValuacionRequest":
        if not self.puntos and not self.nomenclaturas:
            raise ValueError("hace falta al menos un punto o una nomenclatura")
        return self


class ParcelaOut(BaseModel):
    nomenclatura: str
    origen: Literal["punto", "nomenclatura", "ambos"]
    nro_cuenta: str | None = None
    tipo_parcela: str | None = None
    estado: str | None = None
    desig_oficial: str | None = None
    localidad: str | None = None
    superficie_urbana_m2: Decimal = Decimal("0")
    superficie_rural_m2: Decimal = Decimal("0")
    valuacion: Decimal = Decimal("0")
    valuacion_tierra: Decimal = Decimal("0")
    valuacion_mejoras: Decimal = Decimal("0")
    vigencia_desde: date | None = None
    # Mapa de valores de la tierra (spec §4.2) — referencia de mercado, NO valor fiscal
    valor_mercado: Decimal | None = None
    vut_pesos_m2: Decimal | None = None
    vur_pesos_ha: Decimal | None = None


class ValuacionResponse(BaseModel):
    parcelas: list[ParcelaOut]
    valor_total: Decimal
    valor_tierra: Decimal
    valor_mejoras: Decimal
    valor_mercado: Decimal | None
    mercado_anio: int | None
    mercado_parcelas_sin_valor: int
    vigencia_desde: date | None
    puntos_sin_parcela: list[PuntoIn]
    nomenclaturas_no_encontradas: list[str]
