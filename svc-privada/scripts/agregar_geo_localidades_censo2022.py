"""Agrega a `priv_geo_localidades` las 7 localidades reales que estaban
ausentes del padrón geográfico, descubiertas al cruzar el Censo Nacional
2022 (ver `cargar_habitantes_censo2022.py` en esta misma carpeta y
`docs/data/geo_localidades.json`, id_geo 561-567). Departamento y
coordenadas confirmados por fuente externa (Wikipedia/municipio/INDEC),
2026-09-17. Mismas 7 filas que `services/svc-vivienda/scripts/
agregar_geo_localidades_censo2022.py` agrega a `viv_geo_localidades`
(bases separadas, ADR-001 — hay que correr los dos scripts).

RE-1: re-ejecutable — sólo inserta las filas que todavía no existen (por
id_geo). No pisa nada si ya se corrió antes.

Uso (con DATABASE_URL apuntando a db_privada — vía cloud-sql-proxy si es
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

from app.territorial.models import GeoLocalidad  # noqa: E402

NUEVAS = [
    {"id_geo": "561", "departamento": "SAN JUSTO", "localidad": "Brinkmann",
     "lat": -30.866944, "lon": -62.033611},
    {"id_geo": "562", "departamento": "TERCERO ARRIBA", "localidad": "James Craik",
     "lat": -32.161389, "lon": -63.467778},
    {"id_geo": "563", "departamento": "SANTA MARÍA", "localidad": "Bouwer",
     "lat": -31.558333, "lon": -64.192222},
    {"id_geo": "564", "departamento": "TULUMBA", "localidad": "Lucio Victorio Mansilla",
     "lat": -29.807222, "lon": -64.712778},
    {"id_geo": "565", "departamento": "MARCOS JUAREZ", "localidad": "Capitán General Bernardo O'Higgins",
     "lat": -33.2485, "lon": -62.2692},
    {"id_geo": "566", "departamento": "RÍO PRIMERO", "localidad": "Kilómetro 658",
     "lat": -31.37, "lon": -63.529722},
    {"id_geo": "567", "departamento": "MARCOS JUAREZ", "localidad": "Colonia Barge",
     "lat": -33.255833, "lon": -62.604167},
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
