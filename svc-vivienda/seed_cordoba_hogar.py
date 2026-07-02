"""
Script para seedear los estados y localidades del Programa Córdoba Hogar.
Ejecutar con Cloud SQL Proxy activo:

  cloud_sql_proxy -instances=gestorcooperativo:southamerica-east1:ministerio-postgres=tcp:5432 &
  DATABASE_URL="postgresql+asyncpg://svc_vivienda:PASS@127.0.0.1:5432/db_vivienda" python seed_cordoba_hogar.py

Primero correr la migración 0006:
  alembic upgrade 0006
"""
import asyncio
import os
import sys
from datetime import date

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(__file__))

from app.cordoba_hogar.models import ConfigCordobaHogar, EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordoba_hogar.seed_data import ESTADOS_SEED, LOCALIDADES_SEED

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://svc_vivienda:password@127.0.0.1:5432/db_vivienda",
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def main():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(delete(LocalidadCordobaHogar))
            await db.execute(delete(EstadoCordobaHogar))
            await db.execute(delete(ConfigCordobaHogar))

            for e in ESTADOS_SEED:
                db.add(EstadoCordobaHogar(**e))
            await db.flush()
            print(f"  {len(ESTADOS_SEED)} estados insertados")

            for loc in LOCALIDADES_SEED:
                loc_data = dict(loc)
                if loc_data.get('fecha_anuncio'):
                    loc_data['fecha_anuncio'] = date.fromisoformat(loc_data['fecha_anuncio'])
                db.add(LocalidadCordobaHogar(**loc_data))
            await db.flush()
            print(f"  {len(LOCALIDADES_SEED)} localidades insertadas")

            db.add(ConfigCordobaHogar(id=1, presupuesto=0))
            await db.flush()
            print("  Config inicializada")

    print("✅ Seed cordoba hogar completado")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
