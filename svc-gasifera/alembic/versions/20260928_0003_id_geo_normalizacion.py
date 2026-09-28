"""id_geo/match_tipo resueltos en sync-time contra el padrón de svc-vivienda

ADR-024 / docs/files/spec-normalizacion-localidades.md §4.5

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gas_pit_acciones_territorio", sa.Column("id_geo", sa.String(20)))
    op.add_column("gas_pit_acciones_territorio", sa.Column("match_tipo", sa.String(20)))
    op.add_column("gas_pit_obras_localidades", sa.Column("id_geo", sa.String(20)))
    op.add_column("gas_pit_obras_localidades", sa.Column("match_tipo", sa.String(20)))


def downgrade() -> None:
    op.drop_column("gas_pit_obras_localidades", "match_tipo")
    op.drop_column("gas_pit_obras_localidades", "id_geo")
    op.drop_column("gas_pit_acciones_territorio", "match_tipo")
    op.drop_column("gas_pit_acciones_territorio", "id_geo")
