"""normalizacion de localidades — viv_geo_alias_manual + localidad_id en CC/CH
+ backfill CC/CH/ML

ADR-024 / docs/files/spec-normalizacion-localidades.md

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-28
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.geo.matching import candidatos_localidad, normalize_name
from app.geo.seed_data import ALIAS_MANUAL_SEED

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def _resolver(
    dep_in: str | None,
    loc_in: str | None,
    padron_por_nombre: dict[str, list[tuple[str, str]]],
    alias: dict[str, str | None],
) -> tuple[str | None, str | None]:
    """Mismo algoritmo que `app.geo.service._resolver_uno`, reimplementado acá
    sobre tuplas planas (sin ORM/async) para poder correr dentro de la
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
            dep_norm = normalize_name(dep_in)
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

    # ── viv_geo_alias_manual ─────────────────────────────────────────────────
    op.create_table(
        "viv_geo_alias_manual",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("texto_normalizado", sa.String(200), nullable=False),
        sa.Column("texto_original", sa.String(200), nullable=False),
        sa.Column("id_geo", sa.String(20), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("origen", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.ForeignKeyConstraint(["id_geo"], ["viv_geo_localidades.id_geo"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("texto_normalizado", name="uq_geo_alias_manual_texto_normalizado"),
    )

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
        for row in ALIAS_MANUAL_SEED
    ])

    # ── localidad_id / localidad_match_tipo en CC y CH ───────────────────────
    for tabla in ("viv_cordon_cuneta", "viv_cordoba_hogar"):
        op.add_column(tabla, sa.Column("localidad_id", sa.String(20), nullable=True))
        op.add_column(tabla, sa.Column("localidad_match_tipo", sa.String(20), nullable=True))
        op.create_foreign_key(
            f"fk_{tabla}_localidad_id", tabla, "viv_geo_localidades", ["localidad_id"], ["id_geo"]
        )
        op.execute(f"""
            CREATE UNIQUE INDEX uq_{tabla}_localidad_id_activo
            ON {tabla} (localidad_id)
            WHERE deleted_at IS NULL AND localidad_id IS NOT NULL
        """)

    # ── localidad_match_tipo en Mi Lugar (ya tenía localidad_id) ─────────────
    op.add_column("viv_ml_proyectos", sa.Column("localidad_match_tipo", sa.String(20), nullable=True))

    # ── Backfill best-effort (CC, CH, ML) ─────────────────────────────────────
    padron_por_nombre: dict[str, list[tuple[str, str]]] = {}
    for id_geo, dep, loc, activo in conn.execute(sa.text(
        "SELECT id_geo, departamento, localidad, activo FROM viv_geo_localidades"
    )).fetchall():
        if not activo:
            continue
        padron_por_nombre.setdefault(normalize_name(loc), []).append((id_geo, normalize_name(dep)))

    alias: dict[str, str | None] = {}
    for texto_normalizado, id_geo in conn.execute(sa.text(
        "SELECT texto_normalizado, id_geo FROM viv_geo_alias_manual"
    )).fetchall():
        alias[texto_normalizado] = id_geo

    _backfill(conn, "viv_cordon_cuneta", "municipio", padron_por_nombre, alias)
    _backfill(conn, "viv_cordoba_hogar", "localidad", padron_por_nombre, alias)
    _backfill(conn, "viv_ml_proyectos", "localidad_nombre", padron_por_nombre, alias)


def downgrade() -> None:
    op.drop_column("viv_ml_proyectos", "localidad_match_tipo")
    op.execute("DROP INDEX IF EXISTS uq_viv_cordoba_hogar_localidad_id_activo")
    op.drop_constraint("fk_viv_cordoba_hogar_localidad_id", "viv_cordoba_hogar", type_="foreignkey")
    op.drop_column("viv_cordoba_hogar", "localidad_match_tipo")
    op.drop_column("viv_cordoba_hogar", "localidad_id")
    op.execute("DROP INDEX IF EXISTS uq_viv_cordon_cuneta_localidad_id_activo")
    op.drop_constraint("fk_viv_cordon_cuneta_localidad_id", "viv_cordon_cuneta", type_="foreignkey")
    op.drop_column("viv_cordon_cuneta", "localidad_match_tipo")
    op.drop_column("viv_cordon_cuneta", "localidad_id")
    op.drop_table("viv_geo_alias_manual")
