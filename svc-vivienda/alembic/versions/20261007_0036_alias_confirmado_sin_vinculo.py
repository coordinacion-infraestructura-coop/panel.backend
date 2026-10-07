"""Localidades "confirmado sin vínculo": barrios de Mi Lugar y Paraje El Barrial

Decisión del usuario 2026-10-07 (docs/files/spec-privada-padron-oficial.md
§1.2, ADR-026): hay nombres que no van a matchear nunca contra el padrón
oficial y eso es correcto, no un error a corregir —

- "Barrio Chingolo" y "Santa Teresa": proyectos de Mi Lugar que son loteos
  nombrados por barrio de Córdoba Capital, no por localidad.
- "Paraje El Barrial" (Tulumba): gestión de Privada sobre un paraje que no
  está en el padrón.

Se registran en `viv_geo_alias_manual` con `id_geo = NULL` — mismo mecanismo
que "Santiago Temple" (spec-normalizacion-localidades.md §4.2): el resolver
los devuelve como `match_tipo="manual"` sin `id_geo` y dejan de generar la
notificación de "localidad sin resolver" en cada corrida.

De paso marca `localidad_match_tipo = 'manual'` en los proyectos de Mi Lugar
ya cargados con esos nombres (hoy lo tienen en NULL), para que el dato refleje
lo mismo que devolvería el resolver al editarlos.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-07
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.geo.matching import normalize_name

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_CREATED_BY = "migracion-confirmado-sin-vinculo"

# (texto_original, motivo, origen)
_SIN_VINCULO = [
    ("Barrio Chingolo", "loteo de Mi Lugar nombrado por barrio de Córdoba Capital — no es una localidad del padrón", "mi_lugar"),
    ("Santa Teresa", "loteo de Mi Lugar nombrado por barrio de Córdoba Capital — no es una localidad del padrón", "mi_lugar"),
    ("Paraje El Barrial", "paraje de Tulumba ausente del padrón — gestión de Privada", "privada"),
]


def upgrade() -> None:
    conn = op.get_bind()
    existentes = {
        fila[0] for fila in conn.execute(sa.text("SELECT texto_normalizado FROM viv_geo_alias_manual")).fetchall()
    }
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
    nuevos = [
        {
            "id": str(uuid.uuid4()),
            "texto_normalizado": normalize_name(texto),
            "texto_original": texto,
            "id_geo": None,
            "motivo": motivo,
            "origen": origen,
            "created_at": now,
            "created_by": _CREATED_BY,
        }
        for texto, motivo, origen in _SIN_VINCULO
        if normalize_name(texto) not in existentes
    ]
    if nuevos:
        op.bulk_insert(alias_tbl, nuevos)

    confirmados = {normalize_name(texto) for texto, _, origen in _SIN_VINCULO if origen == "mi_lugar"}
    for proy_id, nombre in conn.execute(sa.text(
        "SELECT id, localidad_nombre FROM viv_ml_proyectos "
        "WHERE localidad_id IS NULL AND localidad_match_tipo IS NULL AND deleted_at IS NULL"
    )).fetchall():
        if normalize_name(nombre) in confirmados:
            conn.execute(
                sa.text("UPDATE viv_ml_proyectos SET localidad_match_tipo = 'manual' WHERE id = :id"),
                {"id": proy_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM viv_geo_alias_manual WHERE created_by = :cb"), {"cb": _CREATED_BY}
    )
