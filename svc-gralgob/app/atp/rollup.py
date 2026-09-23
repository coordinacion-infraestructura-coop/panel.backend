"""Rollup territorial para federación server-side hacia `resumen_territorial`
de svc-vivienda (mismo patrón que ADR-016 usó para svc-privada y ADR-021 para
svc-gasifera).

Consumido únicamente por el endpoint interno IAM-only
`GET /internal/atp/rollup-territorial` — nunca por el frontend.
"""
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp.models import AtpCompromiso, AtpCronogramaPago


def _as_float(v: Any) -> float | None:
    return float(v) if v is not None else None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


async def rollup_territorial(db: AsyncSession) -> list[dict]:
    """Rollup global por (departamento, localidad) sobre atp_compromisos +
    atp_cronograma_pagos. `entregado_sum` es la suma en valor absoluto del
    cronograma (el signo se mirror-ea del Sheet: negativo = pagado, ver
    `AtpCronogramaPago`) — mismo criterio que `total_pagado` en
    `atp/sync.listar_compromisos`."""
    dep = func.upper(func.trim(AtpCompromiso.departamento))
    loc = func.upper(func.trim(AtpCompromiso.localidad))

    pagado_por_compromiso = (
        select(
            AtpCronogramaPago.compromiso_id.label("compromiso_id"),
            func.sum(AtpCronogramaPago.monto).label("pagado"),
        )
        .group_by(AtpCronogramaPago.compromiso_id)
        .subquery()
    )

    rows = (
        await db.execute(
            select(
                dep.label("departamento"),
                loc.label("localidad"),
                func.count().label("total_compromisos"),
                func.count().filter(AtpCompromiso.derivado.is_(True)).label("derivados"),
                func.sum(AtpCompromiso.monto).label("monto_total_sum"),
                func.sum(func.abs(pagado_por_compromiso.c.pagado)).label("entregado_sum"),
                func.max(AtpCompromiso.fecha_anuncio).label("fecha_max"),
            )
            .select_from(AtpCompromiso)
            .outerjoin(
                pagado_por_compromiso,
                pagado_por_compromiso.c.compromiso_id == AtpCompromiso.id,
            )
            .group_by(dep, loc)
            .order_by(dep, loc)
        )
    ).all()
    return [
        {
            "departamento": r.departamento,
            "localidad": r.localidad,
            "total_compromisos": int(r.total_compromisos),
            "derivados": int(r.derivados),
            "monto_total_sum": _as_float(r.monto_total_sum),
            "entregado_sum": _as_float(r.entregado_sum) or 0.0,
            "fecha_max": _iso(r.fecha_max),
        }
        for r in rows
    ]
