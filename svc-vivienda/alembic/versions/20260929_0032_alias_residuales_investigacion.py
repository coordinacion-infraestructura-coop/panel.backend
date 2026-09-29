"""6 alias adicionales de la investigación de los ~30 casos residuales (ATP/Gasífera/Privada)

Pedido explícito del usuario (2026-09-29): investigar uno por uno los casos
que quedaron sin resolver tras el primer backfill (migración 0031). De ~14
localidades reales con problemas:
- 6 eran typos/variantes de una fuente con un único candidato claro en el
  padrón (o confirmados por el usuario cuando no eran tan literales) — se
  agregan acá.
- 7 resultaron ser DUPLICADOS dentro del propio padrón (`viv_geo_localidades`
  tiene dos filas para la misma localidad real, con id_geo distinto y
  coordenadas a metros/pocos km una de otra — ej. "Charbonier" con id_geo 555
  y 141 en Punilla). Esto NO se toca acá — queda documentado para revisión
  manual del padrón, fuera de alcance de esta spec (afecta la fuente de
  verdad que usan todos los servicios, no un caso puntual).
- 2 quedan genuinamente sin resolver (mismo criterio que "Santiago Temple"):
  "KILOMETRO 658" (Río Primero, Gasífera) y "PARAJE EL BARRIAL" (Tulumba,
  Privada) — no aparecen en el padrón bajo ningún nombre cercano.

ADR-024 / docs/files/spec-normalizacion-localidades.md

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-29
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.geo.matching import candidatos_localidad, normalize_departamento, normalize_name
from app.geo.seed_data import ALIAS_MANUAL_SEED_20260929

revision = "0032"
down_revision = "0031"
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
        for row in ALIAS_MANUAL_SEED_20260929
    ])

    # Re-backfill (sólo filas todavía sin localidad_id) — CC/CH ya están al
    # 100%, esto es por consistencia con las migraciones anteriores y por si
    # ML tiene algo nuevo, no porque se espere mucho movimiento acá.
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
    for row in ALIAS_MANUAL_SEED_20260929:
        conn.execute(
            sa.text("DELETE FROM viv_geo_alias_manual WHERE texto_normalizado = :t"),
            {"t": row["texto_normalizado"]},
        )
