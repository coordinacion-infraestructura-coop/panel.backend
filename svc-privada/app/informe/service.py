"""Informe de Cooperativas — 4 endpoints de agregación (paridad Anexo D).

Port de `routers/informe_cooperativas.py` + `sql_informe_cooperativas.py` del sistema
viejo. La clasificación en temas (regex sobre `detalle`) está en `clasificacion.py`.
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import as_float, iso
from app.gestiones.models import Gestion
from app.informe.clasificacion import entra_al_informe, es_ministerio_cooperativas

DEFAULT_DESDE = date(2025, 12, 1)


async def _filas(db: AsyncSession, desde: date, hasta: date) -> list[dict]:
    """Filas del 'v_informe_cooperativas' entre [desde, hasta] por fecha_ingreso."""
    rows = (
        await db.execute(select(Gestion).where(Gestion.deleted_at.is_(None)))
    ).scalars().all()
    out = []
    for g in rows:
        entra, tema = entra_al_informe(g.categoria_general_id, g.detalle, g.ministerio_agencia_id)
        if not entra:
            continue
        if g.fecha_ingreso is None or not (desde <= g.fecha_ingreso <= hasta):
            continue
        out.append({
            "id_gestion": g.id,
            "tema": tema,
            "es_ministerio_cooperativas": es_ministerio_cooperativas(g.ministerio_agencia_id),
            "estado": g.estado,
            "urgencia": g.urgencia,
            "departamento": g.departamento,
            "localidad": g.localidad,
            "fecha_ingreso": g.fecha_ingreso,
            "detalle": g.detalle,
            "nro_expediente": g.nro_expediente,
            "lat": as_float(g.lat),
            "lon": as_float(g.lon),
        })
    return out


async def resumen(db: AsyncSession, desde: date, hasta: date) -> dict:
    filas = await _filas(db, desde, hasta)
    por_tema: dict = defaultdict(lambda: {"total": 0, "finalizadas": 0, "en_curso": 0, "archivadas": 0, "urgentes": 0})
    for f in filas:
        b = por_tema[f["tema"]]
        b["total"] += 1
        if f["estado"] == "FINALIZADA":
            b["finalizadas"] += 1
        if f["estado"] not in ("FINALIZADA", "ARCHIVADO"):
            b["en_curso"] += 1
        if f["estado"] == "ARCHIVADO":
            b["archivadas"] += 1
        if f["urgencia"] == "Alta":
            b["urgentes"] += 1
    rows = [{"tema": t, **v} for t, v in por_tema.items()]
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {
        "total": sum(r["total"] for r in rows),
        "fecha_desde": desde.isoformat(),
        "fecha_hasta": hasta.isoformat(),
        "por_tema": rows,
    }


async def temporal(db: AsyncSession, desde: date, hasta: date, tema: str | None) -> list[dict]:
    filas = await _filas(db, desde, hasta)
    agg: dict = defaultdict(int)
    for f in filas:
        if tema and f["tema"] != tema:
            continue
        mes = f["fecha_ingreso"].strftime("%Y-%m")
        agg[(mes, f["tema"])] += 1
    rows = [{"mes": m, "tema": t, "total": n} for (m, t), n in agg.items()]
    rows.sort(key=lambda r: (r["mes"], r["tema"] or ""))
    return rows


async def por_departamento(db: AsyncSession, desde: date, hasta: date, tema: str | None) -> list[dict]:
    filas = await _filas(db, desde, hasta)
    agg: dict = defaultdict(lambda: {"total": 0, "finalizadas": 0})
    for f in filas:
        if tema and f["tema"] != tema:
            continue
        b = agg[(f["tema"], f["departamento"])]
        b["total"] += 1
        if f["estado"] == "FINALIZADA":
            b["finalizadas"] += 1
    rows = [{"tema": t, "departamento": d, **v} for (t, d), v in agg.items()]
    rows.sort(key=lambda r: (r["tema"] or "", -r["total"]))
    return rows


async def puntos(db: AsyncSession, desde: date, hasta: date, tema: str | None) -> list[dict]:
    filas = await _filas(db, desde, hasta)
    out = []
    for f in filas:
        if tema and f["tema"] != tema:
            continue
        if f["lat"] is None or f["lon"] is None:
            continue
        out.append({
            "id_gestion": f["id_gestion"],
            "tema": f["tema"],
            "es_ministerio_cooperativas": f["es_ministerio_cooperativas"],
            "estado": f["estado"],
            "urgencia": f["urgencia"],
            "departamento": f["departamento"],
            "localidad": f["localidad"],
            "fecha_ingreso": iso(f["fecha_ingreso"]),
            "detalle_corto": (f["detalle"] or "")[:160],
            "nro_expediente": f["nro_expediente"],
            "lat": f["lat"],
            "lon": f["lon"],
        })
    out.sort(key=lambda r: r["fecha_ingreso"] or "", reverse=True)
    return out
