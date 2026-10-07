"""priv_localidades_info.id_geo — vínculo al padrón oficial (ADR-026)

docs/files/spec-privada-padron-oficial.md (approved) §3.4. Columna nullable;
la completa `POST /internal/privada/geo/normalizar-gestiones`. La clave
primaria por texto (departamento, localidad) no se toca.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("priv_localidades_info", sa.Column("id_geo", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("priv_localidades_info", "id_geo")
