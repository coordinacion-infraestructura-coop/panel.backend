"""18 alias de la primera carga real de transferencias (svc-datos-externos, ADR-025)

Investigación uno por uno de los 21 grupos (departamento, nombre_pdf) que
quedaron con `id_geo IS NULL` en `ext_transferencias` tras la primera carga a
producción (Municipios+Comunas, julio 2026). 16 con un único candidato claro
en el padrón (abreviatura/espaciado/singular-plural), 2 de confianza media
(marcados en el motivo), y 1 que se agrega con `id_geo=None` para no seguir
disparando la notificación de "sin resolver" en cada sync mensual futuro
("Kilometro 658" — mismo caso que la migración 0032). "Santiago Temple" NO se
re-agrega — ya existe como alias con `id_geo=None` desde el seed original
(origen "atp"); `texto_normalizado` es UNIQUE, duplicarlo rompe la migración
(confirmado al correrla contra prod). Un tercer caso ("TTOTAL Río Segundo")
tampoco se agrega como alias — es una fila de TOTAL del PDF mal parseada como
si fuera una localidad, el problema está en el parser de svc-datos-externos,
no en el matching geográfico; queda fuera de esta migración.

Esta migración sólo agrega los alias (para que la PRÓXIMA llamada a
`/internal/geo/resolver-localidades` resuelva bien) — no toca
`ext_transferencias` (vive en `db_datos_externos`, otra base). Las filas ya
cargadas se corrigen re-subiendo los mismos PDFs al endpoint
`cargar-manual` después de este deploy (upsert por `(periodo, tipo,
nombre_pdf, concepto)`).

ADR-024 / ADR-025 / docs/files/spec-normalizacion-localidades.md

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-01
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.geo.matching import candidatos_localidad, normalize_departamento, normalize_name
from app.geo.seed_data import ALIAS_MANUAL_SEED_20261001

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def _resolver(
    dep_in: str | None,
    loc_in: str | None,
    padron_por_nombre: dict[str, list[tuple[str, str]]],
    alias: dict[str, str | None],
) -> tuple[str | None, str | None]:
    """Mismo algoritmo que `app.geo.service._resolver_uno` — reimplementado
    sobre tuplas planas para poder correr dentro de la migración."""
    if not loc_in:
        return None, None
    loc_norm = normalize_name(loc_in)

    if loc_norm in alias:
        return alias[loc_norm], "manual"

    candidatos = [(loc_norm, "exacto")]
    candidatos += [(k, "alias") for k in candidatos_localidad(loc_in) if k != loc_norm]
    for cand, tipo in candidatos:
        filas = padron_por_nombre.get(cand)
        if not filas:
            continue
        if len(filas) == 1:
            return filas[0][0], tipo
        if dep_in:
            dep_norm = normalize_departamento(dep_in)
            exactos = [f for f in filas if f[1] == dep_norm]
            if len(exactos) == 1:
                return exactos[0][0], tipo
    return None, None


def _backfill(conn, tabla: str, campo_nombre: str, padron_por_nombre, alias) -> None:
    rows = conn.execute(sa.text(
        f"SELECT id, departamento, {campo_nombre} FROM {tabla} "
        f"WHERE deleted_at IS NULL AND localidad_id IS NULL"
    )).fetchall()
    for row_id, dep, nombre in rows:
        id_geo, tipo = _resolver(dep, nombre, padron_por_nombre, alias)
        if id_geo:
            conn.execute(
                sa.text(
                    f"UPDATE {tabla} SET localidad_id = :id_geo, localidad_match_tipo = :tipo "
                    f"WHERE id = :row_id"
                ),
                {"id_geo": id_geo, "tipo": tipo, "row_id": row_id},
            )


def upgrade() -> None:
    conn = op.get_bind()

    alias_tbl = sa.table(
        "viv_geo_alias_manual",
        sa.column("id", sa.String()),
        sa.column("texto_normalizado", sa.String()),
        sa.column("texto_original", sa.String()),
        sa.column("id_geo", sa.String()),
        sa.column("motivo", sa.Text()),
        sa.column("origen", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.String()),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(alias_tbl, [
        {"id": str(uuid.uuid4()), "created_at": now, **row}
        for row in ALIAS_MANUAL_SEED_20261001
    ])

    # Re-backfill por consistencia con las migraciones anteriores (0031/0032) —
    # no se espera movimiento real acá, estos alias son específicos de la
    # grafía del PDF de transferencias, no de CC/CH/ML.
    padron_por_nombre: dict[str, list[tuple[str, str]]] = {}
    for id_geo, dep, loc, activo in conn.execute(sa.text(
        "SELECT id_geo, departamento, localidad, activo FROM viv_geo_localidades"
    )).fetchall():
        if not activo:
            continue
        for key in candidatos_localidad(loc):
            padron_por_nombre.setdefault(key, []).append((id_geo, normalize_departamento(dep)))

    alias: dict[str, str | None] = {}
    for texto_normalizado, id_geo in conn.execute(sa.text(
        "SELECT texto_normalizado, id_geo FROM viv_geo_alias_manual"
    )).fetchall():
        alias[texto_normalizado] = id_geo

    _backfill(conn, "viv_cordon_cuneta", "municipio", padron_por_nombre, alias)
    _backfill(conn, "viv_cordoba_hogar", "localidad", padron_por_nombre, alias)
    _backfill(conn, "viv_ml_proyectos", "localidad_nombre", padron_por_nombre, alias)


def downgrade() -> None:
    conn = op.get_bind()
    for row in ALIAS_MANUAL_SEED_20261001:
        conn.execute(
            sa.text("DELETE FROM viv_geo_alias_manual WHERE texto_normalizado = :t"),
            {"t": row["texto_normalizado"]},
        )
