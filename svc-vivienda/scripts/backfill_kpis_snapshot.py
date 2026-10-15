"""Backfill one-off de `viv_resumen_territorial_snapshot.kpis` (migración 0040).

Para cada día (hora de Argentina) en que ningún snapshot tiene `kpis`, calcula los KPIs del
último snapshot de ese día y los guarda. Idempotente: los días que ya tienen `kpis` se saltean.
El avance de obra no está en el payload del snapshot, así que en la historia rellenada
`avance_obra_promedio` queda en null.

Uso (desde services/svc-vivienda/, con DATABASE_URL apuntando a la base):
    python -m scripts.backfill_kpis_snapshot --dry-run
    python -m scripts.backfill_kpis_snapshot

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
    asyncio.run(main(parser.parse_args().dry_run))
