"""ATP Interno para el Tablero de Gobierno (spec-atp-interno.md §4, Etapa 4 del panel).

Solo Admin y Autoridad, sin chequeo de secretaría, como ATP Compromisos. Filtro territorial
por código INDEC (la planilla lo trae en cada fila). **Ningún esquema de este módulo tiene el
referente** (§5). Nunca se suma con ATP Compromisos (ADR-029).

`armar_tablero` y `por_localidad` son puros para poder testear cada cálculo.
"""
from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp_interno.models import AtpInternoPago, AtpInternoSyncLog
from app.auth import ROLES_TABLERO, AuthUser, require_roles
from app.database import get_db

router = APIRouter(prefix="/tablero", tags=["tablero-gobierno"])


class PagoFila(BaseModel):
    fecha: date | None
    anio: int
    codigo_indec: str
    localidad: str | None
    departamento: str | None
    monto: float


class Kpis(BaseModel):
    localidades: int
    pagos: int
    monto: float
    sin_fecha: int  # pagos con fecha rota en la planilla, contados en el año de la planilla
    monto_sin_fecha: float


class Departamento(BaseModel):
    departamento: str
    localidades: int
    pagos: int
    monto: float


class Localidad(BaseModel):
    codigo_indec: str
    localidad: str | None
    departamento: str | None
    pagos: int
    monto: float
    ultimo_pago: date | None


class Periodo(BaseModel):
    kpis: Kpis
    mensual: list[float]  # 12 valores; vacío para la gestión completa
    por_departamento: list[Departamento]
    por_localidad: list[Localidad]


class PeriodoAnio(BaseModel):
    anio: int
    periodo: Periodo


class AtpInternoResponse(BaseModel):
    anios: list[int]
    gestion: Periodo | None
    por_anio: list[PeriodoAnio]
    pagos: list[PagoFila]
    saldo_disponible: float | None  # sin fuente todavía (spec §8.2)
    ultima_sincronizacion: datetime | None
    estado_sincronizacion: str  # ok | error | frenado | sin_datos


class LocalidadMonto(BaseModel):
    codigo_indec: str
    pagos: int
    monto: float


SIN_DATO = "Sin dato"


def _periodo(pagos: list[PagoFila], anio: int | None) -> Periodo:
    mensual = [0.0] * 12
    deptos: dict[str, list[PagoFila]] = defaultdict(list)
    locs: dict[str, list[PagoFila]] = defaultdict(list)
    for p in pagos:
        if anio is not None and p.fecha is not None:
            mensual[p.fecha.month - 1] += p.monto
        deptos[p.departamento or SIN_DATO].append(p)
        locs[p.codigo_indec].append(p)
    sin_fecha = [p for p in pagos if p.fecha is None]
    return Periodo(
        kpis=Kpis(
            localidades=len(locs),
            pagos=len(pagos),
            monto=sum(p.monto for p in pagos),
            sin_fecha=len(sin_fecha),
            monto_sin_fecha=sum(p.monto for p in sin_fecha),
        ),
        mensual=mensual if anio is not None else [],
        por_departamento=sorted(
            (
                Departamento(departamento=d, localidades=len({p.codigo_indec for p in g}), pagos=len(g), monto=sum(p.monto for p in g))
                for d, g in deptos.items()
            ),
            key=lambda x: -x.monto,
        ),
        por_localidad=sorted(
            (
                Localidad(
                    codigo_indec=c,
                    localidad=g[0].localidad,
                    departamento=g[0].departamento,
                    pagos=len(g),
                    monto=sum(p.monto for p in g),
                    ultimo_pago=max((p.fecha for p in g if p.fecha), default=None),
                )
                for c, g in locs.items()
            ),
            key=lambda x: -x.monto,
        ),
    )


def armar_tablero(pagos: list[PagoFila]) -> dict:
    pagos = sorted(pagos, key=lambda p: (p.fecha or date.min, p.codigo_indec), reverse=True)
    anios = sorted({p.anio for p in pagos})
    return {
        "anios": anios,
        "gestion": _periodo(pagos, None) if pagos else None,
        "por_anio": [PeriodoAnio(anio=a, periodo=_periodo([p for p in pagos if p.anio == a], a)) for a in anios],
        "pagos": pagos,
    }


def por_localidad(pagos: list[PagoFila]) -> list[LocalidadMonto]:
    g: dict[str, list[PagoFila]] = defaultdict(list)
    for p in pagos:
        g[p.codigo_indec].append(p)
    return [LocalidadMonto(codigo_indec=c, pagos=len(v), monto=sum(p.monto for p in v)) for c, v in sorted(g.items())]


async def leer_pagos(db: AsyncSession, codigos: list[str] | None = None, anio: int | None = None) -> list[PagoFila]:
    # Se seleccionan columnas explícitas: el referente no sale nunca de la base por acá.
    q = select(
        AtpInternoPago.fecha,
        AtpInternoPago.anio,
        AtpInternoPago.codigo_indec,
        AtpInternoPago.localidad,
        AtpInternoPago.departamento,
        AtpInternoPago.monto,
    )
    if codigos:
        q = q.where(AtpInternoPago.codigo_indec.in_(codigos))
    if anio is not None:
        q = q.where(AtpInternoPago.anio == anio)
    return [
        PagoFila(fecha=f, anio=a, codigo_indec=c, localidad=l, departamento=d, monto=float(m))
        for f, a, c, l, d, m in (await db.execute(q)).all()
    ]


@router.get("/atp-interno", response_model=AtpInternoResponse)
async def tablero_atp_interno(
    codigo_indec: list[str] | None = Query(None, description="Localidades del filtro (vacío = toda la provincia)"),
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*ROLES_TABLERO)),
) -> AtpInternoResponse:
    pagos = await leer_pagos(db, codigo_indec or None)
    log = (
        await db.execute(select(AtpInternoSyncLog).order_by(AtpInternoSyncLog.started_at.desc()).limit(1))
    ).scalar_one_or_none()
    return AtpInternoResponse(
        **armar_tablero(pagos),
        saldo_disponible=None,
        ultima_sincronizacion=log.finished_at if log else None,
        estado_sincronizacion=log.estado if log else "sin_datos",
    )
