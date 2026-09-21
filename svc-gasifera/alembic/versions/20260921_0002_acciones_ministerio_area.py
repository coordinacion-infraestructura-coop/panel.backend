"""gas_pit_acciones_territorio: agregar ministerio y area

El panel preliminar (spec-sync-gasifera-pit.md §12) necesita mostrar estas dos
columnas del Sheet ("Ministerio", "Área") que la Fase 0 no persistía.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gas_pit_acciones_territorio", sa.Column("ministerio", sa.String(150)))
    op.add_column("gas_pit_acciones_territorio", sa.Column("area", sa.String(150)))


def downgrade() -> None:
    op.drop_column("gas_pit_acciones_territorio", "area")
    op.drop_column("gas_pit_acciones_territorio", "ministerio")
