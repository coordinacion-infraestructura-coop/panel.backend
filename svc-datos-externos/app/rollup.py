"""Rollup territorial para federación server-side hacia `resumen_territorial`
de svc-vivienda (ADR-025, mismo patrón que ADR-016/021/022).

Consumido únicamente por `GET /internal/datos-externos/rollup-territorial` —
nunca por el frontend. Devuelve, por `id_geo`, población/viviendas del Censo
2022 y transferencias del último período cargado (total + desglose por
concepto) — mismo espíritu de rollup acotado que ya usan
Privada/Gasífera/Gralgob (no expone todo el modelo interno).

Desde la Fase 1 del Tablero de Gobierno
(spec-datos-externos-fase1-nomenclador-demografia.md §6) suma, de forma
aditiva, `superficie_km2` y `poblacion_2010` (públicos) y el objeto
`ficha_gobierno` (restringido: svc-vivienda sólo lo entrega a los roles
`Admin` y `Autoridad`). La población expuesta sigue siendo la del Censo.

Itera sobre la UNIÓN de `id_geo`s presentes en Censo o en Transferencias, no
sólo sobre Censo — bug real encontrado en producción (2026-10-01, 34
localidades con transferencias bien matcheadas, incluida "Agua de Oro",
desaparecían del rollup porque su fila de Censo había quedado ambigua/sin
`id_geo` — el Censo "Cuadro 1.6" no trae departamento, así que dos
localidades homónimas en departamentos distintos, como las dos "Agua de
Oro" de Colón y Río Segundo, no se pueden desambiguar sólo con el nombre).
"""
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.gobierno.models import CAMPOS_RESTRINGIDOS, ExtGobEnte, ExtGobLocalidad
from app.transferencias.models import ExtTransferencia

_TIPO_A_CATEGORIA = {"municipio": "MU", "comuna": "CO"}


def _as_float(v: Any) -> float | None:
    return float(v) if v is not None else None


async def _ultimo_periodo(db: AsyncSession) -> Any:
    return (await db.execute(select(func.max(ExtTransferencia.periodo)))).scalar_one_or_none()


def _ficha_gobierno(loc: ExtGobLocalidad | None) -> dict | None:
    if loc is None:
        return None
    ficha = {campo: getattr(loc, campo) for campo in CAMPOS_RESTRINGIDOS}
    ficha["masa_salarial"] = _as_float(ficha["masa_salarial"])
    return ficha if any(v is not None for v in ficha.values()) else None


async def zonas_rurales(db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(ExtGobEnte.departamento, ExtGobEnte.poblacion_2022, ExtGobEnte.poblacion_2010)
            .where(ExtGobEnte.tipo_ente == "zona_rural", ExtGobEnte.deleted_at.is_(None))
            .order_by(ExtGobEnte.departamento)
        )
    ).all()
    return [
        {"departamento": r.departamento, "poblacion_2022": r.poblacion_2022, "poblacion_2010": r.poblacion_2010}
        for r in rows
    ]


async def rollup_territorial(db: AsyncSession) -> list[dict]:
    censo_rows = (
        await db.execute(
            select(
                ExtGeoCenso.id_geo,
                ExtGeoCenso.codigo_indec,
                ExtGeoCenso.categoria,
                ExtGeoCenso.poblacion_2022,
                ExtGeoCenso.viviendas_2022,
            ).where(ExtGeoCenso.id_geo.is_not(None), ExtGeoCenso.deleted_at.is_(None))
        )
    ).all()
    censo_por_id_geo = {c.id_geo: c for c in censo_rows}

    gob_rows = (
        await db.execute(
            select(ExtGobLocalidad).where(ExtGobLocalidad.id_geo.is_not(None), ExtGobLocalidad.deleted_at.is_(None))
        )
    ).scalars().all()
    gob_por_id_geo: dict[str, ExtGobLocalidad] = {}
    for g in gob_rows:
        gob_por_id_geo.setdefault(g.id_geo, g)

    ultimo_periodo = await _ultimo_periodo(db)
    transferencias_por_id_geo: dict[str, dict] = {}
    metadata_por_id_geo: dict[str, dict] = {}
    if ultimo_periodo is not None:
        tr_rows = (
            await db.execute(
                select(
                    ExtTransferencia.id_geo,
                    ExtTransferencia.concepto,
                    func.sum(ExtTransferencia.monto).label("monto_sum"),
                )
                .where(ExtTransferencia.periodo == ultimo_periodo, ExtTransferencia.id_geo.is_not(None))
                .group_by(ExtTransferencia.id_geo, ExtTransferencia.concepto)
            )
        ).all()
        for r in tr_rows:
            entry = transferencias_por_id_geo.setdefault(r.id_geo, {"por_concepto": {}, "total": 0.0})
            monto = _as_float(r.monto_sum) or 0.0
            entry["por_concepto"][r.concepto] = monto
            if r.concepto != "total":
                entry["total"] += monto

        # codigo_indec/tipo sólo hacen falta para id_geo que NO tienen fila de
        # censo (si la tienen, esos campos ya vienen de ahí) — consulta aparte
        # para no repetir columnas funcionalmente dependientes en el group_by
        # de arriba.
        # Sin DISTINCT ON (no portable a SQLite, que usan los tests) — se trae
        # todo (6 filas por id_geo como mucho, un concepto por fila) y se
        # dedupea en Python, quedándose con la primera que aparece.
        faltantes = [id_geo for id_geo in transferencias_por_id_geo if id_geo not in censo_por_id_geo]
        if faltantes:
            meta_rows = (
                await db.execute(
                    select(ExtTransferencia.id_geo, ExtTransferencia.codigo_indec, ExtTransferencia.tipo)
                    .where(ExtTransferencia.periodo == ultimo_periodo, ExtTransferencia.id_geo.in_(faltantes))
                )
            ).all()
            for r in meta_rows:
                metadata_por_id_geo.setdefault(r.id_geo, {"codigo_indec": r.codigo_indec, "tipo": r.tipo})

    resultado = []
    for id_geo in censo_por_id_geo.keys() | transferencias_por_id_geo.keys() | gob_por_id_geo.keys():
        c = censo_por_id_geo.get(id_geo)
        g = gob_por_id_geo.get(id_geo)
        tr = transferencias_por_id_geo.get(id_geo)
        meta = metadata_por_id_geo.get(id_geo)
        resultado.append({
            "id_geo": id_geo,
            "codigo_indec": c.codigo_indec if c else (meta["codigo_indec"] if meta else (g.codigo_indec if g else None)),
            "categoria": c.categoria if c else (_TIPO_A_CATEGORIA.get(meta["tipo"]) if meta else (g.tipo if g else None)),
            "poblacion_2022": c.poblacion_2022 if c else None,
            "viviendas_2022": c.viviendas_2022 if c else None,
            "transferencias_periodo": ultimo_periodo.isoformat() if ultimo_periodo else None,
            "transferencias_total": tr["total"] if tr else None,
            "transferencias_por_concepto": tr["por_concepto"] if tr else None,
            "superficie_km2": _as_float(g.superficie_km2) if g else None,
            "poblacion_2010": g.poblacion_2010 if g else None,
            "ficha_gobierno": _ficha_gobierno(g),
        })
    return resultado
