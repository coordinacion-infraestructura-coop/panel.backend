"""ATP histórico 2023–2025 para el Tablero de Gobierno (spec-datos-externos-privada-gobernador.md
§7.4), desde la pestaña `ATP` de la planilla "Gobierno" de la Privada.

Devuelve la misma forma que ATP Interno (`/api/v1/gralgob/tablero/atp-interno`) para que la
pantalla de ATP Interno sume estos años a los suyos: los años no se superponen, porque el sync
corta en `CORTE_ATP_INTERNO`. Sin referente: la columna ni se lee.
"""
from collections import defaultdict
from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_privada.models import ExtGobAtpHistorico
from app.gob_privada.parse import CORTE_ATP_INTERNO
from app.gobierno.models import ExtGobSyncLog
from app.tablero.planillas import _nomenclador

FUENTE = "atp_historico"
SIN_DATO = "Sin dato"


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
    sin_fecha: int
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


class AtpHistoricoResponse(BaseModel):
    concepto: str = "atp-historico"
    corte: date  # desde esta fecha el ATP sale de ATP Interno
    anios: list[int]
    gestion: Periodo | None
    por_anio: list[PeriodoAnio]
    pagos: list[PagoFila]
    ultima_sincronizacion: datetime | None
    estado_sincronizacion: str  # ok | parcial | fallido | sin_datos


def _periodo(pagos: list[PagoFila], anio: int | None) -> Periodo:
    """Mismo cálculo que `svc-gralgob/app/atp_interno/tablero._periodo`."""
    mensual = [0.0] * 12
    deptos: dict[str, list[PagoFila]] = defaultdict(list)
    locs: dict[str, list[PagoFila]] = defaultdict(list)
    for p in pagos:
        if anio is not None and p.fecha is not None:
            mensual[p.fecha.month - 1] += p.monto
        deptos[p.departamento or SIN_DATO].append(p)
        locs[p.codigo_indec].append(p)
    return Periodo(
        kpis=Kpis(localidades=len(locs), pagos=len(pagos), monto=sum(p.monto for p in pagos), sin_fecha=0, monto_sin_fecha=0.0),
        mensual=mensual if anio is not None else [],
        por_departamento=sorted(
            (Departamento(departamento=d, localidades=len({p.codigo_indec for p in g}), pagos=len(g), monto=sum(p.monto for p in g))
             for d, g in deptos.items()),
            key=lambda x: -x.monto,
        ),
        por_localidad=sorted(
            (Localidad(codigo_indec=c, localidad=g[0].localidad, departamento=g[0].departamento, pagos=len(g),
                       monto=sum(p.monto for p in g), ultimo_pago=max(p.fecha for p in g))
             for c, g in locs.items()),
            key=lambda x: -x.monto,
        ),
    )


async def _pagos(db: AsyncSession, codigos: list[str] | None) -> list[PagoFila]:
    q = select(ExtGobAtpHistorico)
    if codigos:
        q = q.where(ExtGobAtpHistorico.codigo_indec.in_(codigos))
    nombres = {loc.codigo_indec: loc for loc in await _nomenclador(db, codigos)}
    pagos = []
    for f in (await db.execute(q)).scalars():
        loc = nombres.get(f.codigo_indec or "")
        pagos.append(PagoFila(
            fecha=f.fecha, anio=f.anio,
            # Sin código (localidad que no está en el nomenclador): se agrupa por el nombre de la planilla.
            codigo_indec=f.codigo_indec or f"sin-codigo:{f.localidad or ''}",
            localidad=loc.nombre_gob if loc else f.localidad, departamento=loc.departamento_gob if loc else f.departamento,
            monto=float(f.monto),
        ))
    return sorted(pagos, key=lambda p: (p.fecha or date.min, p.codigo_indec), reverse=True)


async def get_atp_historico(db: AsyncSession, codigos: list[str] | None) -> AtpHistoricoResponse:
    pagos = await _pagos(db, codigos)
    anios = sorted({p.anio for p in pagos})
    log = (
        await db.execute(select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == FUENTE).order_by(ExtGobSyncLog.corrida_en.desc()).limit(1))
    ).scalar_one_or_none()
    return AtpHistoricoResponse(
        corte=CORTE_ATP_INTERNO,
        anios=anios,
        gestion=_periodo(pagos, None) if pagos else None,
        por_anio=[PeriodoAnio(anio=a, periodo=_periodo([p for p in pagos if p.anio == a], a)) for a in anios],
        pagos=pagos,
        ultima_sincronizacion=log.corrida_en if log else None,
        estado_sincronizacion=log.estado if log else "sin_datos",
    )


async def por_localidad(db: AsyncSession, anio: int) -> dict[str, float] | None:
    """ATP por código INDEC de un año anterior al corte, para el Resumen general. None si el año
    no es histórico o la tabla está vacía (el Resumen lo marca como no disponible)."""
    if anio >= CORTE_ATP_INTERNO.year:
        return None
    if not (await db.execute(select(func.count()).select_from(ExtGobAtpHistorico))).scalar_one():
        return None
    q = (
        select(ExtGobAtpHistorico.codigo_indec, func.sum(ExtGobAtpHistorico.monto))
        .where(ExtGobAtpHistorico.anio == anio, ExtGobAtpHistorico.codigo_indec.is_not(None))
        .group_by(ExtGobAtpHistorico.codigo_indec)
    )
    return {c: float(m) for c, m in (await db.execute(q)).all()}
