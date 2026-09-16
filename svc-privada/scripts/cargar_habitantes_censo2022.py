"""Backfill de `priv_localidades_info.habitantes` con el Censo Nacional 2022
(`docs/data/c2022_cordoba_gobierno_local_c1 (5).xlsx`, hoja "Cuadro 1.6" — Total
de viviendas y población según gobierno local, Provincia de Córdoba).

El censo NO trae departamento — "Jurisdicción" es siempre "Córdoba" (la
provincia entera). El departamento se infiere cruzando por nombre normalizado
contra `priv_geo_localidades` (misma fuente que `viv_geo_localidades`/
`docs/data/geo_localidades.json`). Candidatos por nombre de geo: el nombre
completo, el texto antes del primer paréntesis, el contenido del paréntesis
(y ese contenido sin el prefijo "Est."/"Estación"), y cada parte separada por
" - " — cubre alias como "VICUÑA MACKENNA (Est. Torres)" o
"ELENA - MARIA ELENA".

Los casos ambiguos (mismo nombre de gobierno local matcheando localidades de
2+ departamentos distintos — el censo no da forma de desambiguar) y los sin
match (no aparecen en `priv_geo_localidades` bajo ningún alias reconocido)
quedan AFUERA de esta carga a propósito (decisión del usuario, 2026-09-16).
Usar `--list-unresolved` para ver el detalle completo y resolverlos a mano
después vía `PUT /api/v1/privada/localidades-info`.

RE-1: re-ejecutable. Sobreescribe `habitantes` con el valor del censo para
todo match no ambiguo, exista o no la fila todavía (decisión del usuario: el
censo 2022 es más confiable que cualquier carga/edición previa de habitantes).
No toca ningún otro campo (`electores`, `tipo_localidad`, `color_semaforo`, etc).

Uso (con DATABASE_URL apuntando a db_privada — vía cloud-sql-proxy si es
producción, ver docs/files/CLAUDE.md § Comandos frecuentes):
    python scripts/cargar_habitantes_censo2022.py --list-unresolved   # no toca la DB
    python scripts/cargar_habitantes_censo2022.py --dry-run           # sólo reporta el diff
    python scripts/cargar_habitantes_censo2022.py                     # aplica

Requiere `openpyxl` (no es dependencia del servicio — `pip install openpyxl`
si hace falta, p.ej. en Cloud Shell).
"""
import argparse
import asyncio
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.territorial.models import GeoLocalidad, LocalidadInfo  # noqa: E402

CENSO_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "data" / "c2022_cordoba_gobierno_local_c1 (5).xlsx"
)
ACTOR = "censo2022_script"


def normalize(s) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s).strip())
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", s).strip()


def candidatos(nombre: str) -> set[str]:
    keys = {normalize(nombre)}
    keys.add(normalize(re.split(r"\(", nombre)[0]))
    m = re.search(r"\(([^)]*)\)", nombre)
    if m:
        keys.add(normalize(m.group(1)))
        keys.add(re.sub(r"^(est\.?|estaci[oó]n)\s+", "", normalize(m.group(1))))
    for parte in nombre.split(" - "):
        keys.add(normalize(parte))
    return {k for k in keys if k}


def leer_censo() -> list[dict]:
    """Filas reales de gobierno local (municipio/comuna) de la hoja "Cuadro 1.6":
    excluye el total provincial, "Sin Gobierno Local" (población dispersa, sin
    localidad asignable) y las filas de leyenda/categoría."""
    wb = openpyxl.load_workbook(CENSO_PATH, data_only=True)
    ws = wb["Cuadro 1.6"]
    filas = []
    for row in ws.iter_rows(values_only=True):
        cod_gob_local, categoria, nombre, _viviendas, poblacion = row[2], row[3], row[4], row[5], row[6]
        if not (cod_gob_local is not None and str(cod_gob_local).strip().isdigit()):
            continue
        if not categoria:
            continue  # "Sin Gobierno Local"
        filas.append({"nombre": str(nombre).strip(), "poblacion": int(poblacion)})
    return filas


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="sólo reporta el diff, no escribe")
    ap.add_argument(
        "--list-unresolved", action="store_true",
        help="lista ambiguos + sin-match y termina, sin conectar a la DB",
    )
    args = ap.parse_args()

    censo = leer_censo()

    url = os.environ.get("DATABASE_URL")
    if not url and not args.list_unresolved:
        raise SystemExit(
            "Falta DATABASE_URL (postgresql+asyncpg://user_privada:PASS@127.0.0.1:5432/db_privada)"
        )

    engine = create_async_engine(url) if url else None
    db_cm = AsyncSession(engine, expire_on_commit=False) if engine else None

    async def _run(db: AsyncSession | None):
        if db is not None:
            geo = (await db.execute(select(GeoLocalidad).where(GeoLocalidad.activo.is_(True)))).scalars().all()
            fuente = [(g.departamento, g.localidad) for g in geo]
        else:
            # --list-unresolved sin DATABASE_URL: usa el JSON estático como referencia
            import json
            geo_json = json.loads(
                (Path(__file__).resolve().parents[3] / "docs" / "data" / "geo_localidades.json")
                .read_text(encoding="utf-8")
            )
            fuente = [
                (g["departamento"], g["localidad"]) for g in geo_json if str(g.get("activo")).lower() == "true"
            ]

        geo_index: dict[str, list[tuple[str, str]]] = {}
        for depto, loc in fuente:
            for k in candidatos(loc):
                geo_index.setdefault(k, []).append((depto, loc))

        matches, ambiguos, sin_match = [], [], []
        for fila in censo:
            hits = geo_index.get(normalize(fila["nombre"]))
            if not hits:
                sin_match.append(fila["nombre"])
                continue
            deptos = sorted({h[0] for h in hits})
            if len(deptos) > 1:
                ambiguos.append((fila["nombre"], deptos))
                continue
            depto, localidad = hits[0]
            matches.append({"departamento": depto, "localidad": localidad, "poblacion": fila["poblacion"]})

        print(
            f"censo: {len(censo)} gobiernos locales | "
            f"matches={len(matches)} ambiguos={len(ambiguos)} sin_match={len(sin_match)}"
        )

        if args.list_unresolved:
            print("\n=== AMBIGUOS (mismo nombre, >1 departamento) ===")
            for nombre, deptos in ambiguos:
                print(f"  {nombre} -> {deptos}")
            print("\n=== SIN MATCH (no aparecen en priv_geo_localidades) ===")
            for nombre in sin_match:
                print(f"  {nombre}")
            return

        assert db is not None
        existentes = {
            (r.departamento, r.localidad): r
            for r in (await db.execute(select(LocalidadInfo))).scalars().all()
        }
        ahora = datetime.now(timezone.utc)
        insertados = actualizados = sin_cambio = 0
        for m in matches:
            key = (m["departamento"], m["localidad"])
            actual = existentes.get(key)
            if actual is None:
                print(f"  [INSERT] {m['departamento']} / {m['localidad']}: habitantes=None -> {m['poblacion']}")
                if not args.dry_run:
                    db.add(LocalidadInfo(
                        departamento=m["departamento"], localidad=m["localidad"],
                        habitantes=m["poblacion"],
                        created_at=ahora, created_by=ACTOR,
                        updated_at=ahora, updated_by=ACTOR,
                    ))
                insertados += 1
            elif actual.habitantes != m["poblacion"]:
                print(
                    f"  [UPDATE] {m['departamento']} / {m['localidad']}: "
                    f"habitantes={actual.habitantes} -> {m['poblacion']}"
                )
                if not args.dry_run:
                    actual.habitantes = m["poblacion"]
                    actual.updated_at = ahora
                    actual.updated_by = ACTOR
                actualizados += 1
            else:
                sin_cambio += 1

        if not args.dry_run:
            await db.commit()

        print(
            f"\n{'(dry-run) ' if args.dry_run else ''}"
            f"insertados={insertados} actualizados={actualizados} sin_cambio={sin_cambio}"
        )

    if db_cm is not None:
        async with db_cm as db:
            await _run(db)
        await engine.dispose()
    else:
        await _run(None)


if __name__ == "__main__":
    asyncio.run(main())
