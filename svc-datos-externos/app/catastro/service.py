"""Valuación fiscal y valor de referencia de mercado de un conjunto de parcelas
(docs/files/spec-mi-lugar-valor-fiscal-idecor.md §5.1). Sin estado: no lee ni
escribe `db_datos_externos`; el resultado lo guarda svc-vivienda (ADR-031).

Las parcelas salen de dos lados — las que contienen cada punto y las de la
lista de nomenclaturas — y se unen por `Nomenclatura`.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
from pyproj import Transformer

from app.catastro import idecor
from app.catastro.schemas import ParcelaOut, PuntoIn, ValuacionRequest, ValuacionResponse

logger = logging.getLogger(__name__)

_WGS84_A_GK4 = Transformer.from_crs(4326, 22174, always_xy=True)
_CONCURRENCIA = 5
_CENTAVO = Decimal("0.01")
_M2_POR_HA = Decimal("10000")


@dataclass
class _Parcela:
    props: dict[str, Any]
    origenes: set[str] = field(default_factory=set)
    # En EPSG:22174. Para las que vienen de un punto es ese punto (seguro dentro
    # de la parcela); para las de nomenclatura, el centroide de su geometría.
    interior: tuple[float, float] | None = None


def normalizar_nomenclatura(valor: str) -> str:
    """Solo dígitos: el área puede pegarla con espacios, puntos o guiones."""
    return re.sub(r"\D", "", valor or "")


def _dec(valor: Any) -> Decimal:
    if valor is None or valor == "":
        return Decimal("0")
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _fecha(valor: Any) -> date | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).date()
    except ValueError:
        return None


async def _parcelas_en_punto(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, punto: PuntoIn
) -> tuple[PuntoIn, tuple[float, float], list[dict[str, Any]]]:
    x, y = _WGS84_A_GK4.transform(punto.lng, punto.lat)
    async with sem:
        features = await idecor.get_features(
            client, "parcelas", f"INTERSECTS(geom,{idecor.punto_wkt(x, y)})", idecor.CAMPOS_PARCELA
        )
    return punto, (x, y), features


async def _parcela_por_nomenclatura(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, nomenclatura: str
) -> tuple[str, list[dict[str, Any]]]:
    async with sem:
        features = await idecor.get_features(
            client, "parcelas", f"Nomenclatura='{nomenclatura}'", (*idecor.CAMPOS_PARCELA, "geom")
        )
    return nomenclatura, features


async def _valor_mercado(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, anio: int, parcela: _Parcela
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(valor de mercado, $/m² urbano, $/ha rural). `None` en el valor si a
    alguna de las partes de la parcela le falta valor en el mapa."""
    props = parcela.props
    sup_u = _dec(props.get("Superficie_Tierra_Urbana"))
    sup_r = _dec(props.get("Superficie_Tierra_Rural"))
    if sup_u <= 0 and sup_r <= 0:
        return None, None, None

    vut: Decimal | None = None
    vur: Decimal | None = None
    total = Decimal("0")
    completo = True
    if sup_u > 0:
        async with sem:
            features = await idecor.get_features(
                client, f"valor_tierra_urbana_{anio}",
                f"nomenclatura='{props['Nomenclatura']}'", ("nomenclatura", "vut_pesos"),
            )
        valores = [f["properties"].get("vut_pesos") for f in features if f["properties"].get("vut_pesos") is not None]
        if valores:
            vut = _dec(valores[0]).quantize(_CENTAVO)
            total += vut * sup_u
        else:
            completo = False
    if sup_r > 0:
        if parcela.interior is None:
            completo = False
        else:
            async with sem:
                features = await idecor.get_features(
                    client, f"valor_tierra_rural_{anio}",
                    f"INTERSECTS(geom,{idecor.punto_wkt(*parcela.interior)})", ("vur_pesos",),
                )
            valores = [f["properties"].get("vur_pesos") for f in features if f["properties"].get("vur_pesos") is not None]
            if valores:
                vur = _dec(valores[0]).quantize(_CENTAVO)
                total += vur * sup_r / _M2_POR_HA
            else:
                completo = False
    return (total.quantize(_CENTAVO) if completo else None), vut, vur


async def valuar(req: ValuacionRequest) -> ValuacionResponse:
    """Lanza `idecor.CatastroFallido` si la consulta de parcelas falla entera.
    Si falla solo el mapa de valores, devuelve el valor fiscal igual y el de
    mercado en `None` (spec §5.3)."""
    nomenclaturas = list(dict.fromkeys(n for n in (normalizar_nomenclatura(x) for x in req.nomenclaturas) if n))
    sem = asyncio.Semaphore(_CONCURRENCIA)
    parcelas: dict[str, _Parcela] = {}
    puntos_sin_parcela: list[PuntoIn] = []
    no_encontradas: list[str] = []

    async with idecor._cliente() as client:
        por_punto = await asyncio.gather(*(_parcelas_en_punto(client, sem, p) for p in req.puntos))
        por_nomenclatura = await asyncio.gather(*(_parcela_por_nomenclatura(client, sem, n) for n in nomenclaturas))

        for punto, xy, features in por_punto:
            if not features:
                puntos_sin_parcela.append(punto)
            for f in features:
                props = f["properties"]
                idecor.validar_parcela(props)
                p = parcelas.setdefault(props["Nomenclatura"], _Parcela(props=props))
                p.origenes.add("punto")
                p.interior = p.interior or xy

        for nomenclatura, features in por_nomenclatura:
            if not features:
                no_encontradas.append(nomenclatura)
            for f in features:
                props = f["properties"]
                idecor.validar_parcela(props)
                p = parcelas.setdefault(props["Nomenclatura"], _Parcela(props=props))
                p.origenes.add("nomenclatura")
                p.interior = p.interior or idecor.punto_interior(f.get("geometry"))

        anio: int | None = None
        mercado: dict[str, tuple[Decimal | None, Decimal | None, Decimal | None]] = {}
        try:
            anio = await idecor.anio_mapa_valores(client)
            if anio is not None:
                resultados = await asyncio.gather(
                    *(_valor_mercado(client, sem, anio, p) for p in parcelas.values())
                )
                mercado = dict(zip(parcelas.keys(), resultados))
        except idecor.CatastroFallido as exc:
            logger.warning("catastro: falló el mapa de valores, se devuelve solo el valor fiscal: %s", exc)
            anio, mercado = None, {}

    salida: list[ParcelaOut] = []
    for nomenclatura, p in parcelas.items():
        props = p.props
        valor_mercado, vut, vur = mercado.get(nomenclatura, (None, None, None))
        salida.append(ParcelaOut(
            nomenclatura=nomenclatura,
            origen="ambos" if len(p.origenes) == 2 else next(iter(p.origenes)),
            nro_cuenta=str(props["Nro_Cuenta"]) if props.get("Nro_Cuenta") is not None else None,
            tipo_parcela=props.get("Tipo_Parcela"),
            estado=props.get("Estado"),
            desig_oficial=props.get("desig_oficial"),
            localidad=props.get("localidad"),
            superficie_urbana_m2=_dec(props.get("Superficie_Tierra_Urbana")),
            superficie_rural_m2=_dec(props.get("Superficie_Tierra_Rural")),
            valuacion=_dec(props.get("Valuacion")),
            valuacion_tierra=_dec(props.get("Valuacion_Tierra_Urbana")) + _dec(props.get("Valuacion_Tierra_Rural")),
            valuacion_mejoras=_dec(props.get("Valuacion_Mejoras")),
            vigencia_desde=_fecha(props.get("vigencia_desde")),
            valor_mercado=valor_mercado,
            vut_pesos_m2=vut,
            vur_pesos_ha=vur,
        ))

    con_mercado = [s.valor_mercado for s in salida if s.valor_mercado is not None]
    vigencias = [s.vigencia_desde for s in salida if s.vigencia_desde]
    return ValuacionResponse(
        parcelas=salida,
        valor_total=sum((s.valuacion for s in salida), Decimal("0")).quantize(_CENTAVO),
        valor_tierra=sum((s.valuacion_tierra for s in salida), Decimal("0")).quantize(_CENTAVO),
        valor_mejoras=sum((s.valuacion_mejoras for s in salida), Decimal("0")).quantize(_CENTAVO),
        valor_mercado=sum(con_mercado, Decimal("0")).quantize(_CENTAVO) if con_mercado else None,
        mercado_anio=anio,
        mercado_parcelas_sin_valor=len(salida) - len(con_mercado),
        vigencia_desde=min(vigencias) if vigencias else None,
        puntos_sin_parcela=puntos_sin_parcela,
        nomenclaturas_no_encontradas=no_encontradas,
    )
