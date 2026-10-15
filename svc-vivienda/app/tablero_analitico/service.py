"""Tablero analítico de Vivienda — lectura en vivo de `db_vivienda` (ADR-030).

Reusa el armado de líneas del Resumen Territorial (`resumen_territorial.lineas`) para tener una
sola lógica, pero no lee el snapshot: los expedientes salen de la base de origen en cada pedido.
La serie histórica (Tendencias) sí sale de los snapshots, de su columna `kpis`.

Spec: docs/files/spec-vivienda-tablero-analitico.md §4
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.checklist_tecnico import estado_tecnico
from app.resumen_territorial import aggregations
from app.resumen_territorial import lineas as lineas_mod
from app.resumen_territorial.models import ResumenTerritorialSnapshot
from app.resumen_territorial.service import VER_TODO, comunicacion_visible
from app.tablero_analitico.schemas import ExpedienteTablero, PuntoTendencia, TableroAnaliticoResponse

AREA = "vivienda"


def verificar_acceso(actor: AuthUser) -> None:
    """`Admin`/`Autoridad` siempre; el resto necesita la secretaría Vivienda (§4.2) — misma
    regla que `resumen_territorial.service.filtrar_por_visibilidad`."""
    if actor.role not in VER_TODO and AREA not in (actor.secretarias or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SIN_ACCESO_AREA", "message": "El tablero analítico requiere la secretaría Vivienda"},
        )


async def _denominador(db: AsyncSession, geo: list[dict]) -> dict[str, int]:
    """Gobiernos locales por departamento. Ese recorte lo calcula el Resumen Territorial con
    datos de `svc-datos-externos`; se toma de su último snapshot en vez de volver a federar.
    Sin snapshot: el padrón activo completo."""
    row = (
        await db.execute(
            select(ResumenTerritorialSnapshot.payload)
            .order_by(ResumenTerritorialSnapshot.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    por_depto = (row or {}).get("total_localidades_por_departamento") or {}
    return por_depto or aggregations.contar_localidades_por_departamento(geo)


async def get_tablero(db: AsyncSession, actor: AuthUser) -> TableroAnaliticoResponse:
    verificar_acceso(actor)
    geo = await lineas_mod.geo_rows(db)
    lineas = await lineas_mod.lineas_vivienda(db)

    montos: dict[str, dict[str, float | None]] = {"cc": {}, "ch": {}, "ml": {}}
    for ln in lineas:
        p = ln["programa"]
        montos[aggregations.PROGRAMA_A_CHECKLIST[p["programa"]]][p["entidad_id"]] = p["monto"]
    obra = {cod: await estado_tecnico.avance_por_entidad(db, cod, m) for cod, m in montos.items()}

    ver_todo = actor.role in VER_TODO
    secs = set(actor.secretarias or [])
    expedientes: list[ExpedienteTablero] = []
    for g in aggregations.agrupar_por_localidad(lineas, geo):
        for p in g["programas"]:
            cod = aggregations.PROGRAMA_A_CHECKLIST[p["programa"]]
            o = obra[cod].get(p["entidad_id"], estado_tecnico.RESUMEN_OBRA_VACIO)
            uc = p["ultima_comunicacion"]
            if uc and not ver_todo and not comunicacion_visible(uc.get("area"), secs):
                uc = {**uc, "texto": None}
            expedientes.append(
                ExpedienteTablero(
                    **{k: v for k, v in p.items() if k not in ("area", "ultima_comunicacion")},
                    ultima_comunicacion=uc,
                    localidad=g["localidad"],
                    departamento=g["departamento"],
                    id_geo=g["id_geo"],
                    lat=g["lat_centro"],
                    lon=g["lon_centro"],
                    avance_obra_pct=o["avance_obra_pct"],
                    avance_obra_fecha=o["avance_obra_fecha"],
                    fecha_fin_obra=o["fecha_fin_obra"],
                    hitos_obra=o["hitos_obra"],
                )
            )

    por_depto = await _denominador(db, geo)
    return TableroAnaliticoResponse(
        generado_en=datetime.now(timezone.utc),
        total_localidades_padron=sum(por_depto.values()),
        total_localidades_por_departamento=por_depto,
        expedientes=expedientes,
    )


async def get_tendencias(db: AsyncSession, actor: AuthUser, dias: int) -> list[PuntoTendencia]:
    """KPIs de Vivienda del último snapshot con `kpis` de cada día (hora de Argentina),
    ascendente. Los días sin snapshot con `kpis` no aparecen (§4.3)."""
    verificar_acceso(actor)
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    rows = (
        await db.execute(
            select(ResumenTerritorialSnapshot.computed_at, ResumenTerritorialSnapshot.kpis)
            .where(
                ResumenTerritorialSnapshot.computed_at >= desde,
                ResumenTerritorialSnapshot.kpis.is_not(None),
            )
            .order_by(ResumenTerritorialSnapshot.computed_at)
        )
    ).all()
    por_dia: dict[date, dict] = {}
    for computed_at, kpis in rows:
        if kpis and AREA in kpis:
            por_dia[aggregations.dia_ar(computed_at)] = kpis[AREA]  # el último del día pisa
    return [PuntoTendencia(fecha=d, kpis=k) for d, k in sorted(por_dia.items())]
