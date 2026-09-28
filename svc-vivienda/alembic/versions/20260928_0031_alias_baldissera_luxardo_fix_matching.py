"""alias adicionales (Baldisera/Luxardo) + re-backfill con fix de matching por alias del padrón

Encontrado investigando el reporte de "General Baldissera apareciendo dos
veces" en Checklist Técnico (CC vs CH). Dos causas reales distintas:

1. Typos genuinos en Córdoba Hogar (una letra/una palabra) — se resuelven con
   vinculación manual, mismo criterio que el resto de viv_geo_alias_manual
   (ver migración 0030).
2. Bug de matching: el padrón indexaba localidades con alias entre paréntesis
   (ej. "CHARRAS (Villa Colón)") sólo por su nombre completo — una fuente que
   escribe "CHARRAS" a secas no matcheaba (sólo se expandían los alias del
   lado de la fuente, nunca del lado del padrón). Corregido en
   app/geo/service.py y app/resumen_territorial/aggregations.py; esta
   migración re-corre el backfill con la lógica ya corregida, más
   normalize_departamento (colapsa abreviaturas tipo "General"/"Gral") en la
   desambiguación por departamento.

ADR-024 / docs/files/spec-normalizacion-localidades.md

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-28
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.geo.matching import candidatos_localidad, normalize_departamento, normalize_name
from app.geo.seed_data import ALIAS_MANUAL_SEED_20260928

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def _resolver(
    dep_in: str | None,
    loc_in: str | None,
    padron_por_nombre: dict[str, list[tuple[str, str]]],
    alias: dict[str, str | None],
) -> tuple[str | None, str | None]:
    """Mismo algoritmo que `app.geo.service._resolver_uno` (ya corregido),
    reimplementado sobre tuplas planas para poder correr dentro de la
    migración. Duplicado a propósito — una migración debe ser autocontenida."""
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

    # ── Seed de los 2 alias nuevos ────────────────────────────────────────────
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
        for row in ALIAS_MANUAL_SEED_20260928
    ])

    # ── Re-backfill (sólo filas todavía sin localidad_id) con la lógica corregida ──
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
    # No revierte el backfill (no se puede distinguir con certeza qué filas
    # resolvió esta migración vs. la 0030) — sólo retira los 2 alias nuevos.
    conn = op.get_bind()
    for row in ALIAS_MANUAL_SEED_20260928:
        conn.execute(
            sa.text("DELETE FROM viv_geo_alias_manual WHERE texto_normalizado = :t"),
            {"t": row["texto_normalizado"]},
        )
