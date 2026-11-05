"""Genera sql/grants_fuentes.sql desde app/etl/extractores.py (spec §4).

El rol `agente_ro` recibe SELECT sólo sobre las columnas que los extractores leen: si alguien
agrega una columna a un extractor sin regenerar los grants, el refresco de esa fuente falla
(visible en ag_frescura) en lugar de leer de más. Correr desde svc-agente/:

    python sql/generar_grants.py > sql/grants_fuentes.sql
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlglot  # noqa: E402
from sqlglot import exp  # noqa: E402

from app.etl.carga import BASES  # noqa: E402
from app.etl.extractores import FUENTES  # noqa: E402


def columnas_por_tabla(sql: str) -> dict[str, set[str]]:
    arbol = sqlglot.parse_one(sql, read="postgres")
    alias = {}
    tablas = []
    for t in arbol.find_all(exp.Table):
        alias[t.alias_or_name] = t.name
        tablas.append(t.name)
    out: dict[str, set[str]] = defaultdict(set)
    for c in arbol.find_all(exp.Column):
        if c.table:
            out[alias[c.table]].add(c.name)
        elif len(tablas) == 1:
            out[tablas[0]].add(c.name)
        else:
            raise ValueError(f"Columna sin calificar en consulta con varias tablas: {c.sql()}")
    for t in tablas:
        out.setdefault(t, set())
    return out


def main() -> None:
    print("-- GENERADO por sql/generar_grants.py — no editar a mano.")
    print("-- Correr como postgres; cada bloque contra su base (\\connect).")
    for fuente, consultas in FUENTES.items():
        por_tabla: dict[str, set[str]] = defaultdict(set)
        for sql in consultas.values():
            for t, cols in columnas_por_tabla(sql).items():
                por_tabla[t] |= cols
        db = BASES[fuente]
        print(f"\n\\connect {db}")
        print(f"GRANT CONNECT ON DATABASE {db} TO agente_ro;")
        print("GRANT USAGE ON SCHEMA public TO agente_ro;")
        print("ALTER ROLE agente_ro SET default_transaction_read_only = on;")
        for t in sorted(por_tabla):
            cols = ", ".join(sorted(por_tabla[t]))
            print(f"GRANT SELECT ({cols}) ON {t} TO agente_ro;")


if __name__ == "__main__":
    main()
