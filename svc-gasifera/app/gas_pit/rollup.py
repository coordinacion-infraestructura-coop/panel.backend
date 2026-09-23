"""Rollup territorial para federación server-side hacia `resumen_territorial`
de svc-vivienda (ADR-017, mismo patrón que ADR-016 usó para svc-privada).

Consumido únicamente por el endpoint interno IAM-only
`GET /internal/gasifera/rollup-territorial` — nunca por el frontend.
"""
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gas_pit.models import GasPitAccionTerritorio

CUMPLIDO = "CUMPLIDO"


def _as_float(v: Any) -> float | None:
    return float(v) if v is not None else None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


async def rollup_territorial(db: AsyncSession) -> list[dict]:
    """Rollup global por (departamento, localidad) sobre gas_pit_acciones_territorio
    — no incluye gas_pit_obras (presupuesto/contratista), mismo alcance que el
    rollup de Privada, que sólo federa `gestiones`."""
    dep = func.upper(func.trim(GasPitAccionTerritorio.departamento))
    loc = func.upper(func.trim(GasPitAccionTerritorio.localidad))
    est = func.upper(func.trim(GasPitAccionTerritorio.estado))
    rows = (
        await db.execute(
            select(
                dep.label("departamento"),
                loc.label("localidad"),
                func.count().label("total_acciones"),
                func.count().filter(est == CUMPLIDO).label("cumplidas"),
                func.count().filter(est != CUMPLIDO).label("en_curso"),
                func.sum(GasPitAccionTerritorio.monto_inversion_solicitado).label("monto_solicitado_sum"),
                func.sum(GasPitAccionTerritorio.monto_inversion_usd).label("monto_usd_sum"),
                func.max(GasPitAccionTerritorio.fecha).label("fecha_max"),
            )
            .group_by(dep, loc)
            .order_by(dep, loc)
        )
    ).all()
    return [
        {
            "departamento": r.departamento,
            "localidad": r.localidad,
            "total_acciones": int(r.total_acciones),
            "cumplidas": int(r.cumplidas),
            "en_curso": int(r.en_curso),
            "monto_solicitado_sum": _as_float(r.monto_solicitado_sum),
            "monto_usd_sum": _as_float(r.monto_usd_sum),
            "fecha_max": _iso(r.fecha_max),
        }
        for r in rows
    ]
