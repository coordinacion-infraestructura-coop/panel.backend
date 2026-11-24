"""priv_localidades_info: género del intendente o intendenta

docs/files/spec-padron-politico-gobierno-privada.md §2.4 y spec-privada-planificacion-programas.md
§5.1. Lo completa el sync diario del padrón político desde svc-datos-externos.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("priv_localidades_info", sa.Column("intendente_sexo", sa.String(1), nullable=True))
    op.add_column("priv_localidades_info", sa.Column("intendente_sexo_origen", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("priv_localidades_info", "intendente_sexo_origen")
    op.drop_column("priv_localidades_info", "intendente_sexo")
