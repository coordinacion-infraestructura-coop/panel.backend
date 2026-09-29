"""Carga única del Censo 2022 INDEC a nivel gobierno local en ext_geo_censo.

Fuente: docs/data/c2022_cordoba_gobierno_local_c1 (5).xlsx, hoja "Cuadro 1.6"
(427 filas: 260 MU + 167 CO). No es un ETL recurrente — es estático hasta el
próximo censo (spec-resumen-territorial-tablero-v2.md §2.1).

El Cuadro 1.6 NO trae departamento — solo "Jurisdicción" (columna 2, siempre
"Córdoba", la provincia) y "Gobierno local" (columna 5, nombre de
localidad). El matching contra el padrón es por nombre solo, en TODA la
provincia (sin poder acotar por departamento) — mismo criterio que usó
`enriquecer_con_censo` en el prototipo de esta sesión (build_correspondencias.py),
con un cutoff de fuzzy más alto (0.8) que el matching acotado por departamento
que sí puede hacer el ETL de transferencias, precisamente porque acá no hay
forma de descartar candidatos de otro departamento.

`id_geo` se resuelve acá, en la propia migración, contra
docs/data/geo_localidades.json (el mismo padrón que siembra
viv_geo_localidades) — sin llamada de red al endpoint de resolver-localidades
de svc-vivienda (ADR-024): una migración de datos no debe depender de que
otro servicio esté arriba y alcanzable. `departamento_censo` se backfillea
desde el departamento de la localidad geo que matcheó — nunca se fabrica si
no hubo match.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29 00:00:01.000000
"""
import difflib
import json
import os
import re
import unicodedata
import uuid as _uuid

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

FUZZY_CUTOFF = 0.8  # cross-provincia, sin acotar por departamento — más exigente que el 0.55 acotado


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _normalize_name(s: str) -> str:
    s = _strip_accents(s).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cargar_geo() -> list[dict]:
    geo_path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "docs", "data", "geo_localidades.json"
    ))
    with open(geo_path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for row in data:
        if row.get("activo") not in ("true", True):
            continue
        out.append({
            "id_geo": str(row["id_geo"]),
            "departamento": row["departamento"],
            "localidad_norm": _normalize_name(row["localidad"]),
        })
    return out


def _resolver_id_geo(localidad_censo: str, geo: list[dict], por_nombre: dict[str, list[dict]]):
    """Devuelve (id_geo, departamento_geo, match_tipo). Sin acotar por
    departamento (no disponible en la fuente) — un nombre exacto con más de
    un candidato en distintos departamentos queda "ambiguo" (sin id_geo) en
    vez de adivinar, mismo criterio tolerante que el resto del sistema."""
    nombre_norm = _normalize_name(localidad_censo)

    exactos = por_nombre.get(nombre_norm, [])
    if len(exactos) == 1:
        return exactos[0]["id_geo"], exactos[0]["departamento"], "exacto"
    if len(exactos) > 1:
        return None, None, "ambiguo"

    mejor, mejor_score = None, 0.0
    for g in geo:
        score = difflib.SequenceMatcher(None, nombre_norm, g["localidad_norm"]).ratio()
        if score > mejor_score:
            mejor, mejor_score = g, score
    if mejor and mejor_score >= FUZZY_CUTOFF:
        return mejor["id_geo"], mejor["departamento"], "fuzzy"

    return None, None, "sin_match"


def upgrade() -> None:
    import openpyxl

    conn = op.get_bind()

    censo_path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "docs", "data", "c2022_cordoba_gobierno_local_c1 (5).xlsx",
    ))
    wb = openpyxl.load_workbook(censo_path, read_only=True, data_only=True)
    ws = wb["Cuadro 1.6"]

    geo = _cargar_geo()
    por_nombre: dict[str, list[dict]] = {}
    for g in geo:
        por_nombre.setdefault(g["localidad_norm"], []).append(g)

    filas_insertadas = 0
    conteo_match: dict[str, int] = {}
    for row in ws.iter_rows(values_only=True):
        if not row or len(row) < 7:
            continue
        # Header real: Código de jurisdicción, Jurisdicción, Código de
        # gobierno local, Categoría, Gobierno local, Viviendas, Población.
        _cod_jur, _jurisdiccion, cod_gl, categoria, nombre, viviendas, poblacion = row[:7]
        if not isinstance(categoria, str) or categoria.strip() not in ("MU", "CO"):
            continue
        if not cod_gl or not nombre:
            continue

        id_geo, departamento_geo, match_tipo = _resolver_id_geo(str(nombre), geo, por_nombre)
        conteo_match[match_tipo] = conteo_match.get(match_tipo, 0) + 1

        conn.execute(sa.text("""
            INSERT INTO ext_geo_censo
                (id, id_geo, codigo_indec, categoria, departamento_censo, localidad_censo,
                 poblacion_2022, viviendas_2022, match_tipo, created_at)
            VALUES
                (:id, :id_geo, :codigo_indec, :categoria, :departamento_censo, :localidad_censo,
                 :poblacion, :viviendas, :match_tipo, NOW())
            ON CONFLICT (codigo_indec) DO NOTHING
        """), {
            "id": str(_uuid.uuid4()),
            "id_geo": id_geo,
            "codigo_indec": str(cod_gl),
            "categoria": categoria.strip(),
            "departamento_censo": departamento_geo,
            "localidad_censo": str(nombre),
            "poblacion": int(poblacion) if isinstance(poblacion, (int, float)) else None,
            "viviendas": int(viviendas) if isinstance(viviendas, (int, float)) else None,
            "match_tipo": match_tipo,
        })
        filas_insertadas += 1

    wb.close()
    print(f"ext_geo_censo: {filas_insertadas} filas insertadas desde Censo 2022. Match: {conteo_match}")


def downgrade() -> None:
    op.execute("DELETE FROM ext_geo_censo")
