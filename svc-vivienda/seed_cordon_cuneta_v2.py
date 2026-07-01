"""
Script para seedear los estados y municipios del Programa Cordón Cuneta (v2).
Ejecutar con Cloud SQL Proxy activo:

  cloud_sql_proxy -instances=gestorcooperativo:southamerica-east1:ministerio-postgres=tcp:5432 &
  DATABASE_URL="postgresql+asyncpg://svc_vivienda:PASS@127.0.0.1:5432/db_vivienda" python seed_cordon_cuneta_v2.py

Primero correr la migración 0002:
  alembic upgrade 0002
"""
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func

# Asegurar que el path del módulo app esté disponible
sys.path.insert(0, os.path.dirname(__file__))

from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta, ConfigCordonCuneta
from app.cordon_cuneta.seed_data import ESTADOS_SEED, MUNICIPIOS_SEED

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://svc_vivienda:password@127.0.0.1:5432/db_vivienda")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def main():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Borrar datos viejos si existen
            from sqlalchemy import delete
            await db.execute(delete(MunicipioCordonCuneta))
            await db.execute(delete(EstadoCordonCuneta))
            await db.execute(delete(ConfigCordonCuneta))

            # Insertar estados
            for e in ESTADOS_SEED:
                db.add(EstadoCordonCuneta(**e))
            await db.flush()
            print(f"  {len(ESTADOS_SEED)} estados insertados")

            # Insertar municipios
            for m in MUNICIPIOS_SEED:
                db.add(MunicipioCordonCuneta(**m))
            await db.flush()
            print(f"  {len(MUNICIPIOS_SEED)} municipios insertados")

            # Config inicial
            db.add(ConfigCordonCuneta(id=1, presupuesto=0))
            await db.flush()
            print("  Config inicializada")

    print("✅ Seed cordon cuneta v2 completado")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
