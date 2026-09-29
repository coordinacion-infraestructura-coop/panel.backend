"""Rollup territorial para federación server-side hacia `resumen_territorial`
de svc-vivienda (ADR-025, mismo patrón que ADR-016/021/022).

Consumido únicamente por `GET /internal/datos-externos/rollup-territorial` —
nunca por el frontend. Devuelve, por `id_geo`, población/viviendas del Censo
2022 y transferencias del último período cargado (total + desglose por
concepto) — mismo espíritu de rollup acotado que ya usan
Privada/Gasífera/Gralgob (no expone todo el modelo interno).
"""
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.transferencias.models import ExtTransferencia


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

    ultimo_periodo = await _ultimo_periodo(db)
    transferencias_por_id_geo: dict[str, dict] = {}
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

    resultado = []
    for c in censo_rows:
        tr = transferencias_por_id_geo.get(c.id_geo)
        resultado.append({
            "id_geo": c.id_geo,
            "codigo_indec": c.codigo_indec,
            "categoria": c.categoria,
            "poblacion_2022": c.poblacion_2022,
            "viviendas_2022": c.viviendas_2022,
            "transferencias_periodo": ultimo_periodo.isoformat() if ultimo_periodo else None,
            "transferencias_total": tr["total"] if tr else None,
            "transferencias_por_concepto": tr["por_concepto"] if tr else None,
        })
    return resultado
