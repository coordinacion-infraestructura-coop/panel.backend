"""id_geo/match_tipo resueltos en sync-time contra el padrón de svc-vivienda

ADR-024 / docs/files/spec-normalizacion-localidades.md §4.5

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("atp_compromisos", sa.Column("id_geo", sa.String(20)))
    op.add_column("atp_compromisos", sa.Column("match_tipo", sa.String(20)))


def downgrade() -> None:
    op.drop_column("atp_compromisos", "match_tipo")
    op.drop_column("atp_compromisos", "id_geo")
