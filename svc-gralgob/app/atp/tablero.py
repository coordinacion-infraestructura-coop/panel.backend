"""ATP Compromisos para el Tablero de Gobierno (spec-tablero-gobierno-panel.md, Etapa 1).

Lectura sobre lo ya sincronizado de la planilla "ATP - Compromiso Gobernador", agregada para
el tablero: KPIs, por ministerio, por estado de pago, por departamento y la lista filtrada.
Solo Admin y Autoridad, sin chequeo de secretaría (vista transversal). Nunca se suma con ATP
Interno (ADR-029, paraguas §3.3).

`armar_tablero` es puro (sin base) para poder testear cada cálculo.
"""
from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp import sync as atp_sync
from app.atp.schemas import CompromisoResponse
from app.auth import ROLES_TABLERO, AuthUser, require_roles
from app.database import get_db

router = APIRouter(prefix="/tablero", tags=["tablero-gobierno"])

SIN_DATO = "Sin dato"


def estado_pago(monto: float | None, pagado: float) -> str:
    """Mismo criterio que el badge de ATP en resumen_territorial (`resumen_atp_estado`)."""
    if not monto or monto <= 0:
        return SIN_DATO
    if pagado <= 0:
        return "Pendiente"
    if pagado >= monto:
        return "Pagado"
    return "Parcial"


class AtpKpis(BaseModel):
    localidades: int
    compromisos: int
    derivados: int
    monto: float
    pagado: float
    saldo: float


class AtpGrupo(BaseModel):
    clave: str
    cantidad: int
    monto: float
    pagado: float


class AtpFila(BaseModel):
    id: str
    fecha_anuncio: date | None
    departamento: str | None
    localidad: str | None
    id_geo: str | None
    ministerio: str | None
    destino: str | None
    nro_expediente: str | None
    derivado: bool
    monto: float | None
    pagado: float
    estado: str


class AtpTableroResponse(BaseModel):
    kpis: AtpKpis
    por_ministerio: list[AtpGrupo]
    por_estado: list[AtpGrupo]
    por_departamento: list[AtpGrupo]
    filas: list[AtpFila]
    ultima_sincronizacion: datetime | None
    estado_sincronizacion: str  # "ok" | "con_errores" | "en_curso" | "sin_datos"


def _agrupar(filas: list[AtpFila], clave) -> list[AtpGrupo]:
    g: dict[str, list[AtpFila]] = defaultdict(list)
    for f in filas:
        g[clave(f) or SIN_DATO].append(f)
    grupos = [
        AtpGrupo(clave=k, cantidad=len(v), monto=sum(f.monto or 0 for f in v), pagado=sum(f.pagado for f in v))
        for k, v in g.items()
    ]
    return sorted(grupos, key=lambda x: -x.monto)


def armar_tablero(items: list[CompromisoResponse], ids_geo: set[str] | None) -> dict:
    """Filtra por id_geo (si viene) y arma KPIs, grupos y filas. `pagado` es el valor absoluto
    del cronograma (la planilla lo trae negativo), como `entregado_sum` del rollup."""
    filas = [
        AtpFila(
            id=c.id,
            fecha_anuncio=c.fecha_anuncio,
            departamento=c.departamento,
            localidad=c.localidad,
            id_geo=c.id_geo,
            ministerio=c.ministerio_destino,
            destino=c.destino,
            nro_expediente=c.nro_expediente,
            derivado=c.derivado,
            monto=c.monto,
            pagado=abs(c.total_pagado or 0.0),
            estado=estado_pago(c.monto, abs(c.total_pagado or 0.0)),
        )
        for c in items
        if ids_geo is None or c.id_geo in ids_geo
    ]
    filas.sort(key=lambda f: (f.fecha_anuncio or date.min), reverse=True)
    monto = sum(f.monto or 0 for f in filas)
    pagado = sum(f.pagado for f in filas)
    orden_estado = {"Pagado": 0, "Parcial": 1, "Pendiente": 2, SIN_DATO: 3}
    return {
        "kpis": AtpKpis(
            localidades=len({f.id_geo or f"{f.departamento}|{f.localidad}" for f in filas}),
            compromisos=len(filas),
            derivados=sum(f.derivado for f in filas),
            monto=monto,
            pagado=pagado,
            saldo=monto - pagado,
        ),
        "por_ministerio": _agrupar(filas, lambda f: f.ministerio),
        "por_estado": sorted(_agrupar(filas, lambda f: f.estado), key=lambda x: orden_estado.get(x.clave, 9)),
        "por_departamento": _agrupar(filas, lambda f: f.departamento),
        "filas": filas,
    }


@router.get("/atp-compromisos", response_model=AtpTableroResponse)
async def tablero_atp_compromisos(
    id_geo: list[str] | None = Query(None, description="Localidades del filtro (vacío = toda la provincia)"),
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*ROLES_TABLERO)),
) -> AtpTableroResponse:
    items, _total = await atp_sync.listar_compromisos(db, limit=100_000, offset=0)
    sync = await atp_sync.get_last_sync_status(db)
    if sync is None:
        estado_sync, ultima = "sin_datos", None
    elif sync.finished_at is None:
        estado_sync, ultima = "en_curso", sync.started_at
    else:
        estado_sync, ultima = ("con_errores" if sync.filas_error else "ok"), sync.finished_at
    return AtpTableroResponse(
        **armar_tablero(items, set(id_geo) if id_geo else None),
        ultima_sincronizacion=ultima,
        estado_sincronizacion=estado_sync,
    )
