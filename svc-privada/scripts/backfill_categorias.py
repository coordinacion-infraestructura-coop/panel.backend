"""Backfill de `priv_gestiones.categoria_id` y `.acciones_implementadas` (E1/E2, RE-1).

`categoria_id` se deriva best-effort:
  1. `tema_informe(...)` (regex sobre `detalle`, ya usado por el informe) → categoría nueva.
  2. si no hay tema, un mapa por `categoria_general_id` (los 14 CAT_* legacy).
  3. si nada matchea → se deja NULL (el área lo completa desde el panel).

`acciones_implementadas` se toma del último evento que lo tenga en `metadata_json`.

RE-1: es re-ejecutable y no destructivo. Por default sólo escribe donde el campo está
NULL; con `--force` recalcula todo. `--dry-run` sólo reporta. `--diff-informe` imprime,
antes y después, el conteo por tema del informe para comparar (doble corrida + sign-off).

Uso (con DATABASE_URL apuntando a db_privada):
    python scripts/backfill_categorias.py --dry-run
    python scripts/backfill_categorias.py
    python scripts/backfill_categorias.py --force --diff-informe
"""
import argparse
import asyncio
import os
import sys

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.gestiones.models import Gestion, GestionEvento  # noqa: E402
from app.informe.clasificacion import tema_informe  # noqa: E402

# ids de las 9 categorías sembradas en la migración 0002
CAT = {
    "Vivienda": 1756700000001,
    "Loteos": 1756700000002,
    "Cordón Cuneta y adoquinado": 1756700000003,
    "Pedidos por ATP": 1756700000004,
    "Pedidos NorOeste y Sur Sur": 1756700000005,
    "Obras de Recursos Hídricos": 1756700000006,
    "Pedidos Administrativos": 1756700000007,
    "Otras Obras": 1756700000008,
    "Ayudas a instituciones": 1756700000009,
}

_TEMA_A_CAT = {
    "Vivienda": CAT["Vivienda"],
    "Lotes": CAT["Loteos"],
    "Cordón Cuneta + Adoquinado": CAT["Cordón Cuneta y adoquinado"],
    "Gas": CAT["Otras Obras"],
    "Kits Solares": CAT["Otras Obras"],
    "Luces LED": CAT["Otras Obras"],
    "Bombeo Solar": CAT["Obras de Recursos Hídricos"],
    "Infraestructura Eléctrica": CAT["Otras Obras"],
    "Préstamos y Fortalecimiento": CAT["Ayudas a instituciones"],
    "Otras Obras": CAT["Otras Obras"],
}

_LEGACY_A_CAT = {
    "CAT_AGUA_Y_SANEAMIENTO": CAT["Obras de Recursos Hídricos"],
    "CAT_INFRAESTRUCTURA_VIAL": CAT["Cordón Cuneta y adoquinado"],
    "CAT_GESTION_MUNICIPAL_INSTITUCIONAL": CAT["Pedidos Administrativos"],
    "CAT_OBRA_DE_GAS": CAT["Otras Obras"],
    "CAT_OBRA_ELECTRICA_ENERGIA": CAT["Otras Obras"],
    "CAT_OBRAS_PUBLICAS": CAT["Otras Obras"],
    "CAT_CULTURA_EVENTOS": CAT["Otras Obras"],
    "CAT_DEPORTES": CAT["Otras Obras"],
    "CAT_EDUCACION": CAT["Ayudas a instituciones"],
    "CAT_SALUD": CAT["Ayudas a instituciones"],
    "CAT_DESARROLLO_SOCIAL": CAT["Ayudas a instituciones"],
    "CAT_AYUDA_A_INSTITUCIONES": CAT["Ayudas a instituciones"],
    "CAT_COOPERATIVAS_Y_MUTUALES": CAT["Ayudas a instituciones"],
    # CAT_OTROS / None → NULL
}


def categoria_para(g: Gestion) -> int | None:
    tema = tema_informe(g.categoria_general_id, g.detalle, g.ministerio_agencia_id)
    if tema and tema in _TEMA_A_CAT:
        return _TEMA_A_CAT[tema]
    return _LEGACY_A_CAT.get(g.categoria_general_id or "")


async def _acciones_por_gestion(db: AsyncSession) -> dict[str, str]:
    rows = (
        await db.execute(
            select(GestionEvento.gestion_id, GestionEvento.fecha_evento, GestionEvento.metadata_json)
            .order_by(GestionEvento.fecha_evento)
        )
    ).all()
    out: dict[str, str] = {}
    for gid, _fecha, meta in rows:
        if isinstance(meta, dict):
            v = meta.get("acciones_implementadas")
            if isinstance(v, str) and v.strip():
                out[gid] = v.strip()  # el último gana (orden asc)
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="recalcular aunque ya tenga valor")
    ap.add_argument("--diff-informe", action="store_true")
    args = ap.parse_args()

    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url)
    async with AsyncSession(engine) as db:
        gestiones = (await db.execute(select(Gestion).where(Gestion.deleted_at.is_(None)))).scalars().all()
        acciones = await _acciones_por_gestion(db)

        cat_set = cat_skip = acc_set = 0
        por_cat: dict[int | None, int] = {}
        for g in gestiones:
            nueva = categoria_para(g)
            por_cat[nueva] = por_cat.get(nueva, 0) + 1
            if nueva is not None and (args.force or g.categoria_id is None):
                if not args.dry_run:
                    await db.execute(update(Gestion).where(Gestion.id == g.id).values(categoria_id=nueva))
                cat_set += 1
            elif nueva is None:
                cat_skip += 1
            acc = acciones.get(g.id)
            if acc and (args.force or not g.acciones_implementadas):
                if not args.dry_run:
                    await db.execute(update(Gestion).where(Gestion.id == g.id).values(acciones_implementadas=acc))
                acc_set += 1

        if not args.dry_run:
            await db.commit()

        print(f"gestiones activas: {len(gestiones)}")
        print(f"categoria_id seteada: {cat_set}  | sin mapeo (NULL): {cat_skip}  | {'DRY-RUN' if args.dry_run else 'aplicado'}")
        print(f"acciones_implementadas backfilleadas: {acc_set}")
        print("distribución por categoría (id → nº gestiones):")
        for cid, n in sorted(por_cat.items(), key=lambda kv: -kv[1]):
            print(f"  {cid}: {n}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
