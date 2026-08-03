import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.cordoba_hogar.models import (
    ConfigCordobaHogar,
    EstadoCordobaHogar,
    EstadoHistorialCH,
    LocalidadCordobaHogar,
)
from app.cordon_cuneta.models import EstadoCordonCuneta, EstadoHistorialCC, MunicipioCordonCuneta
from app.geo.models import GeoLocalidad
from app.informes import aggregations
from app.informes.models import InformeSnapshot
from app.informes.schemas import InformePayload

PROGRAMA_CORDON_CUNETA = "cordon_cuneta"
PROGRAMA_CORDOBA_HOGAR = "cordoba_hogar"


async def _geo_rows(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(GeoLocalidad))
    return [
        {
            "departamento": g.departamento,
            "localidad": g.localidad,
            "lat_centro": g.lat_centro,
            "lon_centro": g.lon_centro,
            "activo": g.activo,
        }
        for g in result.scalars().all()
    ]


def _armar_payload(
    programa: str,
    entidades: list[aggregations.EntidadDict],
    catalogo: dict[int, aggregations.CatalogoEstado],
    geo: list[dict],
    historial: list[dict],
    monto_total: float,
    metricas_extra: dict[str, float | int],
) -> InformePayload:
    por_depto = aggregations.cobertura_por_departamento(entidades, geo)
    return InformePayload(
        programa=programa,
        total_entidades=len(entidades),
        monto_total=monto_total,
        metricas_extra=metricas_extra,
        departamentos_cubiertos=sum(1 for d in por_depto if d["cantidad"] > 0),
        por_estado_general=aggregations.kpis_por_estado(entidades, catalogo),
        por_departamento=por_depto,
        evolucion_temporal=aggregations.evolucion_temporal(historial),
        puntos=aggregations.puntos_mapa(entidades, geo, catalogo),
    )


async def compute_informe_cordon_cuneta(db: AsyncSession) -> InformePayload:
    municipios = (
        await db.execute(
            select(MunicipioCordonCuneta).where(MunicipioCordonCuneta.deleted_at.is_(None))
        )
    ).scalars().all()
    catalogo_rows = (await db.execute(select(EstadoCordonCuneta))).scalars().all()
    historial_rows = (await db.execute(select(EstadoHistorialCC))).scalars().all()
    geo = await _geo_rows(db)

    catalogo = {
        c.id: {"label": c.label, "bg": c.bg, "text_color": c.text_color, "orden": c.orden}
        for c in catalogo_rows
    }
    entidades: list[aggregations.EntidadDict] = [
        {
            "id": m.id,
            "nombre": m.municipio,
            "departamento": m.departamento,
            "estado_general": m.estado_general,
            "expediente": m.expediente,
            "monto": float(m.monto) if m.monto is not None else None,
        }
        for m in municipios
    ]
    historial = [{"created_at": h.created_at} for h in historial_rows]

    monto_total = sum(float(m.monto) for m in municipios if m.monto is not None)
    metricas_extra = {
        "cordon_cuneta_ml_total": sum(
            float(m.cordon_cuneta_ml) for m in municipios if m.cordon_cuneta_ml is not None
        ),
        "adoquinado_m2_total": sum(
            float(m.adoquinado_m2) for m in municipios if m.adoquinado_m2 is not None
        ),
    }
    return _armar_payload(
        PROGRAMA_CORDON_CUNETA, entidades, catalogo, geo, historial, monto_total, metricas_extra
    )


async def compute_informe_cordoba_hogar(db: AsyncSession) -> InformePayload:
    localidades = (
        await db.execute(
            select(LocalidadCordobaHogar).where(LocalidadCordobaHogar.deleted_at.is_(None))
        )
    ).scalars().all()
    catalogo_rows = (await db.execute(select(EstadoCordobaHogar))).scalars().all()
    historial_rows = (await db.execute(select(EstadoHistorialCH))).scalars().all()
    geo = await _geo_rows(db)
    config = (
        await db.execute(select(ConfigCordobaHogar).where(ConfigCordobaHogar.id == 1))
    ).scalar_one_or_none()

    catalogo = {
        c.id: {"label": c.label, "bg": c.bg, "text_color": c.text_color, "orden": c.orden}
        for c in catalogo_rows
    }
    entidades: list[aggregations.EntidadDict] = [
        {
            "id": l.id,
            "nombre": l.localidad,
            "departamento": l.departamento,
            "estado_general": l.estado_general,
            "expediente": l.expediente,
            "monto": float(l.monto) if l.monto is not None else None,
        }
        for l in localidades
    ]
    historial = [{"created_at": h.created_at} for h in historial_rows]

    monto_total = sum(float(l.monto) for l in localidades if l.monto is not None)
    metricas_extra = {
        "cantidad_casas_total": sum(
            l.cantidad_casas for l in localidades if l.cantidad_casas is not None
        ),
        "monto_por_casa": float(config.monto_por_casa) if config and config.monto_por_casa is not None else 0.0,
    }
    return _armar_payload(
        PROGRAMA_CORDOBA_HOGAR, entidades, catalogo, geo, historial, monto_total, metricas_extra
    )


_COMPUTE_FN = {
    PROGRAMA_CORDON_CUNETA: compute_informe_cordon_cuneta,
    PROGRAMA_CORDOBA_HOGAR: compute_informe_cordoba_hogar,
}


async def get_last_snapshot(db: AsyncSession, programa: str) -> InformeSnapshot | None:
    result = await db.execute(
        select(InformeSnapshot)
        .where(InformeSnapshot.programa == programa)
        .order_by(InformeSnapshot.computed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def actualizar_informe(db: AsyncSession, programa: str, actor: AuthUser) -> InformeSnapshot:
    t0 = time.monotonic()
    payload = await _COMPUTE_FN[programa](db)
    duracion_ms = int((time.monotonic() - t0) * 1000)

    snapshot = InformeSnapshot(
        programa=programa,
        payload=payload.model_dump(mode="json"),
        computed_at=datetime.now(timezone.utc),
        computed_by=actor.email,
        duracion_ms=duracion_ms,
    )
    db.add(snapshot)
    await db.flush()
    await log_audit(
        db, actor=actor, action="ACTUALIZAR_INFORME",
        resource_type=f"informe_{programa}", resource_id=programa,
        payload={"total_entidades": payload.total_entidades, "duracion_ms": duracion_ms},
    )
    await db.refresh(snapshot)
    return snapshot
