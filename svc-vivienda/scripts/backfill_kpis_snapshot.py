"""Backfill one-off de `viv_resumen_territorial_snapshot.kpis` (migración 0040).

Para cada día (hora de Argentina) en que ningún snapshot tiene `kpis`, calcula los KPIs del
último snapshot de ese día y los guarda. Idempotente: los días que ya tienen `kpis` se saltean.
El avance de obra no está en el payload del snapshot, así que en la historia rellenada
`avance_obra_promedio` queda en null.

Con `--completar-claves` (v1.1.0), en cambio, toma el snapshot que lee Tendencias en cada día (el
último con `kpis`) y le agrega sólo las claves de KPI que le falten, sin pisar las existentes — así
la historia gana `localidades_items_faltantes` y el `avance_obra_promedio` ya guardado no se pierde.

Uso (desde services/svc-vivienda/, con DATABASE_URL apuntando a la base):
    python -m scripts.backfill_kpis_snapshot --dry-run
    python -m scripts.backfill_kpis_snapshot
    python -m scripts.backfill_kpis_snapshot --completar-claves --dry-run
    python -m scripts.backfill_kpis_snapshot --completar-claves

Spec: docs/files/spec-vivienda-tablero-analitico.md §4.3
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.resumen_territorial import aggregations
from app.resumen_territorial.models import ResumenTerritorialSnapshot


def completar(actual: dict, nuevos: dict) -> dict:
    """`actual` con las claves de `nuevos` que le falten, por área. Nunca pisa un valor existente."""
    out = {area: dict(v) for area, v in (actual or {}).items()}
    for area, kpis in nuevos.items():
        destino = out.setdefault(area, {})
        for clave, valor in kpis.items():
            destino.setdefault(clave, valor)
    return out


async def completar_claves(dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        filas = (
            await db.execute(
                select(ResumenTerritorialSnapshot.id, ResumenTerritorialSnapshot.computed_at)
                .where(ResumenTerritorialSnapshot.kpis.is_not(None))
                .order_by(ResumenTerritorialSnapshot.computed_at)
            )
        ).all()
        ultimo_por_dia: dict[date, str] = {}
        for snap_id, computed_at in filas:
            ultimo_por_dia[aggregations.dia_ar(computed_at)] = snap_id

        cambiados = 0
        for dia, snap_id in sorted(ultimo_por_dia.items()):
            payload, kpis = (
                await db.execute(
                    select(ResumenTerritorialSnapshot.payload, ResumenTerritorialSnapshot.kpis)
                    .where(ResumenTerritorialSnapshot.id == snap_id)
                )
            ).one()
            nuevos = completar(kpis, aggregations.kpis_por_area(payload.get("localidades") or [], dia))
            if nuevos == kpis:
                continue
            cambiados += 1
            agregadas = sorted(set(nuevos.get("vivienda", {})) - set((kpis or {}).get("vivienda", {})))
            print(f"  {dia}  {snap_id}  vivienda +{agregadas}  "
                  f"localidades_items_faltantes={nuevos.get('vivienda', {}).get('localidades_items_faltantes')}")
            if not dry_run:
                await db.execute(
                    update(ResumenTerritorialSnapshot)
                    .where(ResumenTerritorialSnapshot.id == snap_id)
                    .values(kpis=nuevos)
                )
                await db.commit()

        print(f"{len(ultimo_por_dia)} días con kpis, {cambiados} a completar")
        print("dry-run: no se escribió nada" if dry_run else "listo")


async def main(dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        filas = (
            await db.execute(
                select(
                    ResumenTerritorialSnapshot.id,
                    ResumenTerritorialSnapshot.computed_at,
                    ResumenTerritorialSnapshot.kpis.is_not(None).label("tiene_kpis"),
                ).order_by(ResumenTerritorialSnapshot.computed_at)
            )
        ).all()

        ultimo_por_dia: dict[date, tuple[str, object]] = {}
        dias_con_kpis: set[date] = set()
        for snap_id, computed_at, tiene_kpis in filas:
            dia = aggregations.dia_ar(computed_at)
            ultimo_por_dia[dia] = (snap_id, computed_at)
            if tiene_kpis:
                dias_con_kpis.add(dia)

        pendientes = [(d, v) for d, v in sorted(ultimo_por_dia.items()) if d not in dias_con_kpis]
        print(f"{len(filas)} snapshots, {len(ultimo_por_dia)} días, {len(pendientes)} días a completar")

        for dia, (snap_id, _) in pendientes:
            payload = (
                await db.execute(
                    select(ResumenTerritorialSnapshot.payload).where(ResumenTerritorialSnapshot.id == snap_id)
                )
            ).scalar_one()
            kpis = aggregations.kpis_por_area(payload.get("localidades") or [], dia)
            viv = kpis.get("vivienda", {})
            print(f"  {dia}  {snap_id}  vivienda: {viv.get('programas_activos')} programas, "
                  f"{viv.get('localidades')} localidades")
            if not dry_run:
                await db.execute(
                    update(ResumenTerritorialSnapshot)
                    .where(ResumenTerritorialSnapshot.id == snap_id)
                    .values(kpis=kpis)
                )
                await db.commit()

        print("dry-run: no se escribió nada" if dry_run else "listo")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--completar-claves", action="store_true",
                        help="agrega las claves de KPI nuevas a los días que ya tienen kpis")
    args = parser.parse_args()
    asyncio.run(completar_claves(args.dry_run) if args.completar_claves else main(args.dry_run))
