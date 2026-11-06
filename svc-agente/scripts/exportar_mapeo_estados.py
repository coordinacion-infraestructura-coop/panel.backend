"""Exporta el mapeo de estados (glosario.yaml `mapeo_estados`) para que lo revise cada área.

Lee la capa semántica ya cargada (después del primer `POST /internal/agente/refrescar`) y arma
una planilla CSV por secretaría con cada estado que aparece en los datos, cuántos ítems lo usan
y a qué estado común lo lleva hoy el agente. El área completa la columna `estado_correcto`
solo donde no está de acuerdo; esas filas pasan a `mapeo_estados.<familia>.exactos`.

Uso (desde svc-agente/, con DATABASE_URL apuntando a db_agente, por ejemplo vía cloud-sql-proxy):
    python scripts/exportar_mapeo_estados.py salida/
"""
import asyncio
import csv
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.semantica.glosario import glosario

CONSULTA = """
    SELECT secretaria, programa_nombre AS programa, estado_origen, estado_normalizado,
           COUNT(DISTINCT origen_id) AS cantidad
    FROM ag.ag_programa_items
    GROUP BY 1, 2, 3, 4
    UNION ALL
    SELECT 'privada', 'Gestiones', estado, estado_normalizado, COUNT(*)
    FROM ag.ag_gestiones
    GROUP BY 1, 2, 3, 4
    ORDER BY 1, 2, 5 DESC
"""

COLUMNAS = ["programa", "estado_en_el_sistema", "cantidad", "estado_que_usa_el_agente",
            "estado_correcto", "comentario"]


async def main(destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        filas = (await conn.execute(text(CONSULTA))).all()
    await engine.dispose()

    opciones = " / ".join(glosario()["estados_normalizados"])
    por_secretaria: dict[str, list] = {}
    for f in filas:
        por_secretaria.setdefault(f.secretaria, []).append(f)
    for sec, items in por_secretaria.items():
        ruta = destino / f"mapeo_estados_{sec}.csv"
        # utf-8-sig + ";" para que Excel en español lo abra bien con doble clic.
        with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow([f"Estados posibles: {opciones}. Completar 'estado_correcto' solo si no está de acuerdo."])
            w.writerow(COLUMNAS)
            for f in items:
                w.writerow([f.programa, f.estado_origen or "(vacío)", f.cantidad, f.estado_normalizado, "", ""])
        print(f"{ruta}: {len(items)} estados")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "mapeo_estados")))
