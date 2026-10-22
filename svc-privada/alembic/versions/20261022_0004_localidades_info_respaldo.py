"""priv_localidades_info_respaldo — valor original de intendente y partido (ADR-027)

docs/files/spec-padron-politico-gobierno-privada.md §2.3. Se llena antes de que el sync del
padrón político escriba el valor de Gobierno sobre una fila; nunca se pisa.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "priv_localidades_info_respaldo",
        sa.Column("departamento", sa.String(120), primary_key=True),
        sa.Column("localidad", sa.String(160), primary_key=True),
        sa.Column("id_geo", sa.String(30)),
        sa.Column("intendente_jefe_comunal", sa.String(200)),
        sa.Column("partido_politico", sa.String(200)),
        sa.Column("respaldado_en", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("priv_localidades_info_respaldo")
