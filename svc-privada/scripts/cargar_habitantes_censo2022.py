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

El matching automático dejaba 37 filas sin resolver (10 ambiguas + 27 sin
match); las 37 se resolvieron a mano con el usuario el 2026-09-16/17 y viven
en `OVERRIDES_AMBIGUOS`/`OVERRIDES_ALIAS`/`OVERRIDES_NUEVAS` más abajo:
- `OVERRIDES_AMBIGUOS`: mismo nombre en 2 departamentos — se desambigua por
  `(nombre, población)`, confirmado por el usuario caso por caso.
- `OVERRIDES_ALIAS`: el censo usa un nombre distinto pero la localidad YA
  existe en `priv_geo_localidades` bajo otro alias que el matching
  automático no reconoció (ej. "Santa Catalina Holmberg" censo →
  "SANTA CATALINA (EST. HOLMBERG)" geo) — se usa la grafía del geo, no la
  del censo, para no crear una fila con localidad duplicada.
- `OVERRIDES_NUEVAS`: 10 localidades reales que NO existen en
  `priv_geo_localidades` bajo ningún nombre — departamento confirmado vía
  fuentes oficiales (Wikipedia/municipio/INDEC, ver conversación del
  2026-09-17). Por decisión del usuario, **no** se agregan al padrón
  geográfico (`geo_localidades.json`/`viv_geo_localidades`/
  `priv_geo_localidades`) — sólo quedan en `priv_localidades_info` con el
  nombre tal cual el censo. Esto implica que NO van a aparecer en el
  informe-localidades de vivienda ni en `resumen_territorial`, porque esos
  módulos arrancan del padrón geo, no de `priv_localidades_info`.
  (De las 13 candidatas originales, 3 —Parque Calmayo/Estación General
  Paz/Santiago Temple— resultaron ya existir directo en
  `priv_localidades_info` bajo un nombre más corto, detectado por el
  chequeo de nombre-parecido antes de aplicar; quedan documentadas aparte al
  final de este mismo diccionario, no en las 10 genuinamente nuevas.)

Si después del match automático + los overrides sigue quedando algo sin
resolver, usar `--list-unresolved` para verlo (no debería haber nada: las 37
filas listadas arriba cubren el 100% de lo que el censo 2022 no matcheaba
solo).

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

# Ambiguos: mismo nombre de gobierno local en 2 departamentos — desambiguado
# por (nombre normalizado, población), confirmado por el usuario 2026-09-16.
OVERRIDES_AMBIGUOS: dict[tuple[str, int], tuple[str, str]] = {
    ("los chanaritos", 603): ("CRUZ DEL EJE", "Los Chañaritos"),
    ("los chanaritos", 264): ("RÍO SEGUNDO", "LOS CHAÑARITOS"),
    ("villa sarmiento", 421): ("GRAL ROCA", "VILLA SARMIENTO"),
    ("villa sarmiento", 4736): ("SAN ALBERTO", "VILLA SARMIENTO"),
    ("agua de oro", 3242): ("COLÓN", "AGUA DE ORO"),
    ("la puerta", 2788): ("RÍO PRIMERO", "LA PUERTA"),
    ("san jose", 2803): ("SAN JAVIER", "SAN JOSE"),
    ("san pedro", 4469): ("SAN ALBERTO", "SAN PEDRO"),
    ("villa gutierrez", 344): ("ISCHILÍN", "VILLA GUTIERREZ"),
    ("punta del agua", 237): ("TERCERO ARRIBA", "PUNTA DEL AGUA"),
}

# El censo usa un nombre distinto pero la localidad YA existe en
# priv_geo_localidades bajo otro alias — se usa la grafía del geo.
OVERRIDES_ALIAS: dict[str, tuple[str, str]] = {
    "corral de bustos ifflinger": ("MARCOS JUAREZ", "CORRAL DE BUSTOS"),
    "villa de maria": ("RIO SECO", "VILLA DE MARIA DE RIO SECO"),
    "santa catalina holmberg": ("RÍO CUARTO", "SANTA CATALINA (EST. HOLMBERG)"),
    "miramar de ansenuza": ("SAN JUSTO", "MIRAMAR"),
    "dalmacio velez": ("TERCERO ARRIBA", "DALMACIO VELEZ SARSFIELD"),
    "huanchilla": ("JUÁREZ CELMAN", "HUANCHILLAS"),
    "villa rio icho cruz": ("PUNILLA", "ICHO CRUZ"),
    "san javier y yacanto": ("SAN JAVIER", "SAN JAVIER"),
    "la carolina el potosi": ("RÍO CUARTO", "LA CAROLINA (El PotosI)"),
    "las penas sud": ("RÍO CUARTO", "LAS PEÑAS SUR"),
    "villa candelaria norte": ("RIO SECO", "VILLA CANDELARIA"),
    "pacheco de melo": ("JUÁREZ CELMAN", "ESTACION PACHECO DE MELO"),
    "canada del sauce": ("CALAMUCHITA", "VILLA CAÑADA DEL SAUCE"),
    "saturnino maria laspiur": ("SAN JUSTO", "SATURNINO M. LASPIUR"),
    # Estos 3 NO están en priv_geo_localidades, pero SÍ ya existían directo en
    # priv_localidades_info bajo un nombre más corto (detectado por el chequeo
    # de "similares" del 2026-09-17, antes de aplicar — ver conversación).
    "parque calmayo": ("CALAMUCHITA", "CALMAYO"),
    "estacion general paz": ("COLÓN", "GENERAL PAZ"),
    "santiago temple": ("RÍO SEGUNDO", "SANTIAGO TEMPLE"),
}

# Localidades reales ausentes de priv_geo_localidades. No se agregan al
# padrón geográfico (decisión del usuario, 2026-09-17) — sólo quedan en
# priv_localidades_info, con el nombre tal cual el censo. Departamento
# confirmado vía fuente oficial (Wikipedia/municipio/INDEC).
OVERRIDES_NUEVAS: dict[str, tuple[str, str]] = {
    "montecristo": ("RÍO PRIMERO", "Montecristo"),
    "brinkmann": ("SAN JUSTO", "Brinkmann"),
    "james craik": ("TERCERO ARRIBA", "James Craik"),
    "general levalle": ("PTE ROQUE SAENZ PEÑA", "General Levalle"),
    "bouwer": ("SANTA MARÍA", "Bouwer"),
    "lucio victorio mansilla": ("TULUMBA", "Lucio Victorio Mansilla"),
    "capitan general bernardo o'higgins": ("MARCOS JUAREZ", "Capitán General Bernardo O'Higgins"),
    "kilometro 658": ("RÍO PRIMERO", "Kilómetro 658"),
    "nicolas bruzzone": ("GRAL ROCA", "Nicolás Bruzzone"),
    "colonia barge": ("MARCOS JUAREZ", "Colonia Barge"),
}


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

    # ssl=False: asyncpg intenta negociar TLS por default, y cloud-sql-proxy
    # (que ya cifra la conexión real hacia Cloud SQL) resetea la conexión local
    # en texto plano al recibir el SSLRequest -> "Connection reset by peer".
    engine = create_async_engine(url, connect_args={"ssl": False}) if url else None
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
            nn = normalize(fila["nombre"])
            override = (
                OVERRIDES_AMBIGUOS.get((nn, fila["poblacion"]))
                or OVERRIDES_ALIAS.get(nn)
                or OVERRIDES_NUEVAS.get(nn)
            )
            if override:
                depto, localidad = override
                matches.append({"departamento": depto, "localidad": localidad, "poblacion": fila["poblacion"]})
                continue
            hits = geo_index.get(nn)
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
        todas = (await db.execute(select(LocalidadInfo))).scalars().all()
        existentes = {(r.departamento, r.localidad): r for r in todas}
        print(f"priv_localidades_info: {len(todas)} filas existentes en total")

        # Chequeo de duplicados por nombre parecido: priv_localidades_info puede
        # tener filas que no vienen de priv_geo_localidades (carga manual previa,
        # PUT del panel, etc.) — antes de un INSERT, avisar si ya existe algo con
        # nombre normalizado parecido bajo OTRA clave (departamento/localidad
        # distinta), para no crear una fila duplicada del mismo lugar real.
        existentes_norm = [(d, l, normalize(l)) for (d, l) in existentes]

        def similares(localidad_nueva: str, depto_nuevo: str) -> list[tuple[str, str]]:
            n = normalize(localidad_nueva)
            return [
                (d, l) for d, l, ln in existentes_norm
                if (n in ln or ln in n) and (d, l) != (depto_nuevo, localidad_nueva)
            ]

        ahora = datetime.now(timezone.utc)
        insertados = actualizados = sin_cambio = 0
        for m in matches:
            key = (m["departamento"], m["localidad"])
            actual = existentes.get(key)
            if actual is None:
                parecidos = similares(m["localidad"], m["departamento"])
                if parecidos:
                    print(f"  [WARNING] {m['departamento']} / {m['localidad']}: ya existe algo parecido -> {parecidos} — revisar antes de aplicar")
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
