"""Rollup territorial para federación server-side hacia `resumen_territorial`
de svc-vivienda (ADR-025, mismo patrón que ADR-016/021/022).

Consumido únicamente por `GET /internal/datos-externos/rollup-territorial` —
nunca por el frontend. Devuelve, por `id_geo`, población/viviendas del Censo
2022 y transferencias del último período cargado (total + desglose por
concepto) — mismo espíritu de rollup acotado que ya usan
Privada/Gasífera/Gralgob (no expone todo el modelo interno).

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
from app.transferencias.models import ExtTransferencia

_TIPO_A_CATEGORIA = {"municipio": "MU", "comuna": "CO"}


def _as_float(v: Any) -> float | None:
    return float(v) if v is not None else None


async def _ultimo_periodo(db: AsyncSession) -> Any:
    return (await db.execute(select(func.max(ExtTransferencia.periodo)))).scalar_one_or_none()


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
    for id_geo in censo_por_id_geo.keys() | transferencias_por_id_geo.keys():
        c = censo_por_id_geo.get(id_geo)
        tr = transferencias_por_id_geo.get(id_geo)
        meta = metadata_por_id_geo.get(id_geo)
        resultado.append({
            "id_geo": id_geo,
            "codigo_indec": c.codigo_indec if c else (meta["codigo_indec"] if meta else None),
            "categoria": c.categoria if c else (_TIPO_A_CATEGORIA.get(meta["tipo"]) if meta else None),
            "poblacion_2022": c.poblacion_2022 if c else None,
            "viviendas_2022": c.viviendas_2022 if c else None,
            "transferencias_periodo": ultimo_periodo.isoformat() if ultimo_periodo else None,
            "transferencias_total": tr["total"] if tr else None,
            "transferencias_por_concepto": tr["por_concepto"] if tr else None,
        })
    return resultado
