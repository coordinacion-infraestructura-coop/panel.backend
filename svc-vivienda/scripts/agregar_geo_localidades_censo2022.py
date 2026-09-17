"""Agrega a `viv_geo_localidades` las 7 localidades reales que estaban
ausentes del padrón geográfico, descubiertas al cruzar el Censo Nacional
2022 (ver `services/svc-privada/scripts/cargar_habitantes_censo2022.py` y
`docs/data/geo_localidades.json`, id_geo 561-567). Departamento y
coordenadas confirmados por fuente externa (Wikipedia/municipio/INDEC),
2026-09-17.

RE-1: re-ejecutable — sólo inserta las filas que todavía no existen (por
id_geo). No pisa nada si ya se corrió antes.

Uso (con DATABASE_URL apuntando a db_vivienda — vía cloud-sql-proxy si es
producción, ver docs/files/CLAUDE.md § Comandos frecuentes):
    python scripts/agregar_geo_localidades_censo2022.py --dry-run
    python scripts/agregar_geo_localidades_censo2022.py
"""
import argparse
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.geo.models import GeoLocalidad  # noqa: E402

NUEVAS = [
    {"id_geo": "561", "departamento": "SAN JUSTO", "localidad": "Brinkmann",
     "lat_centro": -30.866944, "lon_centro": -62.033611},
    {"id_geo": "562", "departamento": "TERCERO ARRIBA", "localidad": "James Craik",
     "lat_centro": -32.161389, "lon_centro": -63.467778},
    {"id_geo": "563", "departamento": "SANTA MARÍA", "localidad": "Bouwer",
     "lat_centro": -31.558333, "lon_centro": -64.192222},
    {"id_geo": "564", "departamento": "TULUMBA", "localidad": "Lucio Victorio Mansilla",
     "lat_centro": -29.807222, "lon_centro": -64.712778},
    {"id_geo": "565", "departamento": "MARCOS JUAREZ", "localidad": "Capitán General Bernardo O'Higgins",
     "lat_centro": -33.2485, "lon_centro": -62.2692},
    {"id_geo": "566", "departamento": "RÍO PRIMERO", "localidad": "Kilómetro 658",
     "lat_centro": -31.37, "lon_centro": -63.529722},
    {"id_geo": "567", "departamento": "MARCOS JUAREZ", "localidad": "Colonia Barge",
     "lat_centro": -33.255833, "lon_centro": -62.604167},
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    url = os.environ["DATABASE_URL"]
    # ssl=False: asyncpg intenta negociar TLS por default y cloud-sql-proxy
    # resetea la conexión local en texto plano al recibir el SSLRequest.
    engine = create_async_engine(url, connect_args={"ssl": False})
    async with AsyncSession(engine, expire_on_commit=False) as db:
        existentes_ids = {
            r.id_geo for r in (await db.execute(select(GeoLocalidad))).scalars().all()
        }
        insertados = 0
        for n in NUEVAS:
            if n["id_geo"] in existentes_ids:
                print(f"  [SKIP] id_geo={n['id_geo']} ({n['localidad']}) ya existe")
                continue
            print(f"  [INSERT] {n['departamento']} / {n['localidad']} (id_geo={n['id_geo']})")
            if not args.dry_run:
                db.add(GeoLocalidad(activo=True, **n))
            insertados += 1

        if not args.dry_run:
            await db.commit()
        print(f"\n{'(dry-run) ' if args.dry_run else ''}insertados={insertados}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
