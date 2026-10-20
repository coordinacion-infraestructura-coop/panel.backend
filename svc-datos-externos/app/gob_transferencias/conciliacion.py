"""Conciliación de las planillas de Gobierno contra el scraping de Transparencia y contra los
totales de la Vista (spec-datos-externos-fase2-transferencias.md §4).

Las funciones `conciliar_*` son puras; `calcular` junta los datos de la base. El resultado
solo lleva totales provinciales y códigos de localidad: nunca masa salarial ni otros campos
restringidos.
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_transferencias.models import ExtGobCopa, ExtGobFofindes
from app.gobierno.models import ExtGobLocalidad
from app.transferencias.models import ExtTransferencia

UMBRAL = 0.01  # diferencia relativa a partir de la cual una localidad o un mes se informan
INICIO_GESTION = date(2023, 12, 1)

CONCEPTO_TRANSPARENCIA = {"copa": "coparticipacion_ley_8663", "fofindes": "fofindes"}


def _dif(a: float, b: float) -> float | None:
    if not b:
        return None
    return a / b - 1


def conciliar_mensual(
    planilla: dict[tuple[str, date], float],
    transparencia: dict[tuple[str | None, date], float],
    id_geo_de: dict[str, str],
) -> list[dict]:
    """`planilla`: bruto por (código INDEC, mes); `transparencia`: monto por (id_geo, mes), con
    `id_geo` None para las filas sin vínculo (cuentan en el total, no en el cruce por localidad).
    Devuelve una entrada por mes con dato en alguna de las dos fuentes."""
    tot_p: dict[date, float] = defaultdict(float)
    tot_t: dict[date, float] = defaultdict(float)
    por_geo_p: dict[tuple[str, date], float] = defaultdict(float)
    codigo_de = {g: c for c, g in id_geo_de.items()}
    for (codigo, periodo), monto in planilla.items():
        tot_p[periodo] += monto
        if codigo in id_geo_de:
            por_geo_p[(id_geo_de[codigo], periodo)] += monto
    for (id_geo, periodo), monto in transparencia.items():
        tot_t[periodo] += monto

    salida = []
    for periodo in sorted(set(tot_p) | set(tot_t)):
        con_diferencia, solo_p, solo_t = [], 0, 0
        if periodo in tot_p and periodo in tot_t:
            geos = {g for g, p in por_geo_p if p == periodo} | {g for g, p in transparencia if p == periodo and g}
            for g in sorted(geos):
                mp, mt = por_geo_p.get((g, periodo)), transparencia.get((g, periodo))
                if mp is None:
                    solo_t += 1
                elif mt is None:
                    solo_p += 1
                elif abs(_dif(mp, mt) or 0) > UMBRAL:
                    con_diferencia.append(codigo_de.get(g, g))
        salida.append({
            "periodo": periodo.isoformat(),
            "planilla": round(tot_p[periodo], 2) if periodo in tot_p else None,
            "transparencia": round(tot_t[periodo], 2) if periodo in tot_t else None,
            "diferencia": _dif(tot_p[periodo], tot_t[periodo]) if periodo in tot_p and periodo in tot_t else None,
            "localidades_con_diferencia": con_diferencia,
            "solo_planilla": solo_p,
            "solo_transparencia": solo_t,
        })
    return salida


def conciliar_vista(vista_millones: float | None, candidatos: dict[str, float]) -> list[dict]:
    """Compara el total de la Vista (en millones) con los totales calculados para cada período
    candidato, para descubrir qué período usa la Vista."""
    if vista_millones is None:
        return []
    vista = vista_millones * 1_000_000
    return [
        {"periodo": nombre, "calculado": round(total, 2), "vista": round(vista, 2), "diferencia": _dif(vista, total)}
        for nombre, total in candidatos.items()
    ]


def resumen_para_log(meses: list[dict]) -> list[dict]:
    """Lo que va a `anomalias` del log: solo los meses que no cierran."""
    return [
        {"tipo": "conciliacion_transparencia", **m}
        for m in meses
        if (m["diferencia"] is not None and abs(m["diferencia"]) > UMBRAL) or m["localidades_con_diferencia"]
    ]


async def _mensual_planilla(db: AsyncSession, modelo, anio: int | None) -> dict[tuple[str, date], float]:
    q = select(modelo.codigo_indec, modelo.anio, modelo.mes, func.sum(modelo.bruto)).group_by(
        modelo.codigo_indec, modelo.anio, modelo.mes
    )
    if anio is not None:
        q = q.where(modelo.anio == anio)
    return {(c, date(a, m, 1)): float(s or 0) for c, a, m, s in (await db.execute(q)).all()}


async def _mensual_transparencia(db: AsyncSession, concepto: str, anio: int | None) -> dict[tuple[str | None, date], float]:
    q = select(ExtTransferencia.id_geo, ExtTransferencia.periodo, func.sum(ExtTransferencia.monto)).where(
        ExtTransferencia.concepto == concepto
    ).group_by(ExtTransferencia.id_geo, ExtTransferencia.periodo)
    if anio is not None:
        q = q.where(ExtTransferencia.periodo >= date(anio, 1, 1), ExtTransferencia.periodo <= date(anio, 12, 31))
    out: dict[tuple[str | None, date], float] = defaultdict(float)
    for g, p, s in (await db.execute(q)).all():
        out[(g, date(p.year, p.month, 1))] += float(s or 0)
    return out


async def calcular_transparencia(db: AsyncSession, fuente: str, anio: int | None = None) -> list[dict]:
    modelo = ExtGobCopa if fuente == "copa" else ExtGobFofindes
    id_geo_de = dict(
        (await db.execute(
            select(ExtGobLocalidad.codigo_indec, ExtGobLocalidad.id_geo).where(
                ExtGobLocalidad.deleted_at.is_(None), ExtGobLocalidad.id_geo.is_not(None)
            )
        )).all()
    )
    return conciliar_mensual(
        await _mensual_planilla(db, modelo, anio),
        await _mensual_transparencia(db, CONCEPTO_TRANSPARENCIA[fuente], anio),
        id_geo_de,
    )


async def calcular_vista(db: AsyncSession, hoy: date) -> dict[str, list[dict]]:
    salida: dict[str, list[dict]] = {}
    for fuente, modelo, columna in (
        ("copa", ExtGobCopa, ExtGobLocalidad.copa_vista_m),
        ("fofindes", ExtGobFofindes, ExtGobLocalidad.fofindes_vista_m),
    ):
        vista = (await db.execute(select(func.sum(columna)).where(ExtGobLocalidad.deleted_at.is_(None)))).scalar_one()
        candidatos: dict[str, float] = {}
        for nombre, condicion in (
            (f"año {hoy.year}", modelo.anio == hoy.year),
            ("desde diciembre de 2023", (modelo.anio * 100 + modelo.mes) >= INICIO_GESTION.year * 100 + INICIO_GESTION.month),
            ("toda la planilla", None),
        ):
            for medida, col in (("bruto", modelo.bruto), ("neto", modelo.neto_a_transferir)):
                q = select(func.sum(col))
                if condicion is not None:
                    q = q.where(condicion)
                candidatos[f"{nombre} · {medida}"] = float((await db.execute(q)).scalar_one() or 0)
        salida[fuente] = conciliar_vista(float(vista) if vista is not None else None, candidatos)
    return salida
