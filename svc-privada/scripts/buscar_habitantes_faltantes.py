"""Diagnóstico de solo lectura: para cada localidad activa de
`priv_geo_localidades` sin match de habitantes (mismo criterio que
`app/informe_localidades/service.py` de svc-vivienda: candidatos de alias
por paréntesis/guion en ambos lados), busca candidatos "parecidos" en
`priv_localidades_info` con un chequeo más laxo (sin espacios/puntuación +
similitud de texto) para separar:

  (a) casos recuperables — probablemente el mismo lugar con otro nombre,
      quedan listados para revisar y agregar como override a mano; y
  (b) casos sin candidato — probablemente el censo no reporta población
      para esa localidad por separado (queda englobada en su comuna/
      municipio madre), no hay forma de completarlo sin otra fuente.

No escribe nada. Uso (con DATABASE_URL apuntando a db_privada):
    python scripts/buscar_habitantes_faltantes.py
"""
import difflib
import os
import re
import sys
import unicodedata
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.territorial.models import GeoLocalidad, LocalidadInfo  # noqa: E402


def normalize(s) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s).strip())
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", s).strip()


def loose(s) -> str:
    """normalize + sin espacios ni puntuación, para pescar "Monte Cristo" vs
    "Montecristo" o "Bruzone" vs "Bruzzone"."""
    return re.sub(r"[^a-z0-9]", "", normalize(s))


def candidatos(nombre: str) -> set[str]:
    if not nombre:
        return set()
    keys = {normalize(nombre)}
    keys.add(normalize(re.split(r"\(", nombre)[0]))
    m = re.search(r"\(([^)]*)\)", nombre)
    if m:
        keys.add(normalize(m.group(1)))
        keys.add(re.sub(r"^(est\.?|estaci[oó]n)\s+", "", normalize(m.group(1))))
    for parte in nombre.split(" - "):
        keys.add(normalize(parte))
    return {k for k in keys if k}


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, connect_args={"ssl": False})
    async with AsyncSession(engine, expire_on_commit=False) as db:
        geo = (await db.execute(select(GeoLocalidad).where(GeoLocalidad.activo.is_(True)))).scalars().all()
        info = (await db.execute(select(LocalidadInfo))).scalars().all()

        # índice por candidatos de alias (mismo criterio que el informe en prod)
        info_por_candidato: dict[tuple[str, str], int | None] = {}
        for r in info:
            d = normalize(r.departamento)
            for k in candidatos(r.localidad):
                info_por_candidato[(d, k)] = r.habitantes

        info_loose = [(r.departamento, r.localidad, loose(r.localidad), r.habitantes) for r in info]

        sin_dato = []
        for g in geo:
            d = normalize(g.departamento)
            tiene = any((d, k) in info_por_candidato and info_por_candidato[(d, k)] is not None
                        for k in candidatos(g.localidad))
            if not tiene:
                sin_dato.append(g)

        print(f"activas: {len(geo)} | priv_localidades_info: {len(info)} | sin dato (match actual): {len(sin_dato)}\n")

        recuperables, sin_candidato = [], []
        g_loose_by = None
        for g in sin_dato:
            gl = loose(g.localidad)
            candidatos_fuzzy = []
            for depto, localidad, l2, hab in info_loose:
                if hab is None:
                    continue
                ratio = difflib.SequenceMatcher(None, gl, l2).ratio()
                if gl == l2 or gl in l2 or l2 in gl or ratio >= 0.82:
                    candidatos_fuzzy.append((depto, localidad, hab, round(ratio, 2)))
            if candidatos_fuzzy:
                recuperables.append((g, candidatos_fuzzy))
            else:
                sin_candidato.append(g)

        print(f"=== RECUPERABLES ({len(recuperables)}): probable mismo lugar con otro nombre ===")
        for g, cands in recuperables:
            print(f"  {g.departamento} / {g.localidad}  ->  {cands}")

        print(f"\n=== SIN CANDIDATO ({len(sin_candidato)}): probablemente el censo no reporta población separada ===")
        for g in sin_candidato:
            print(f"  {g.departamento} / {g.localidad}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
