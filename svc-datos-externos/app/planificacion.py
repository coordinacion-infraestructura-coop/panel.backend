"""Datos por localidad para la planificación de programas de svc-privada (ADR-036,
docs/files/spec-privada-planificacion-programas.md §5.1 / §6).

Consumido sólo por `GET /internal/datos-externos/planificacion/localidades`, con IAM. Por cada
`id_geo` devuelve dos cosas:

- `coparticipacion_anual`: lo que la localidad recibió por coparticipación (concepto
  `coparticipacion_ley_8663` de `ext_transferencias`) en los **últimos 12 meses publicados**.
  La ventana se mide desde el último mes cargado de ese concepto en toda la provincia, no por
  localidad: si a una localidad le falta un mes, `meses` lo dice.
- `visita_gobernador`: la planilla "2. RECORRIDO Y VISITAS", pestaña `Visitas Gober`
  (`ext_gob_visita_gobernador`). Es la única fuente: ya no se infiere de ATP. Nunca se exponen
  `INTENDENTE` ni `PARTIDO` (de todos modos no se leen, spec fase 5 §5).
"""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_gestion.models import ExtGobVisitaGobernador
from app.gobierno.models import ExtGobLocalidad
from app.transferencias.models import ExtTransferencia

CONCEPTO_COPARTICIPACION = "coparticipacion_ley_8663"
MESES_VENTANA = 12


def _restar_meses(d: date, meses: int) -> date:
    total = d.year * 12 + (d.month - 1) - meses
    return date(total // 12, total % 12 + 1, 1)


async def datos_por_localidad(db: AsyncSession) -> dict:
    hasta = (
        await db.execute(
            select(func.max(ExtTransferencia.periodo)).where(ExtTransferencia.concepto == CONCEPTO_COPARTICIPACION)
        )
    ).scalar_one_or_none()

    por_geo: dict[str, dict] = {}
    desde = None
    if hasta is not None:
        hasta = date(hasta.year, hasta.month, 1)
        desde = _restar_meses(hasta, MESES_VENTANA - 1)
        filas = (
            await db.execute(
                select(
                    ExtTransferencia.id_geo,
                    func.sum(ExtTransferencia.monto),
                    func.count(func.distinct(ExtTransferencia.periodo)),
                )
                .where(
                    ExtTransferencia.concepto == CONCEPTO_COPARTICIPACION,
                    ExtTransferencia.id_geo.is_not(None),
                    ExtTransferencia.periodo >= desde,
                    ExtTransferencia.periodo < _restar_meses(hasta, -1),  # hasta el fin del último mes
                )
                .group_by(ExtTransferencia.id_geo)
            )
        ).all()
        for id_geo, monto, meses in filas:
            por_geo.setdefault(id_geo, {})["coparticipacion_anual"] = {
                "monto": float(monto or 0),
                "meses": int(meses),
            }

    visitas = (
        await db.execute(
            select(ExtGobLocalidad.id_geo, ExtGobVisitaGobernador.visitada, ExtGobVisitaGobernador.fecha_ultima)
            .join(ExtGobLocalidad, ExtGobLocalidad.codigo_indec == ExtGobVisitaGobernador.codigo_indec)
            .where(ExtGobLocalidad.id_geo.is_not(None), ExtGobLocalidad.deleted_at.is_(None))
        )
    ).all()
    for id_geo, visitada, fecha in visitas:
        por_geo.setdefault(id_geo, {})["visita_gobernador"] = {
            "visitada": bool(visitada),
            "fecha_ultima": fecha.isoformat() if fecha else None,
        }

    return {
        "coparticipacion_periodo": (
            {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "meses_ventana": MESES_VENTANA}
            if hasta is not None else None
        ),
        "localidades": [{"id_geo": g, **datos} for g, datos in sorted(por_geo.items())],
    }
