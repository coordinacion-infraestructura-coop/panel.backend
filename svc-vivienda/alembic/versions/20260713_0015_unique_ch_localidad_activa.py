"""unique_ch_localidad_activa

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-13
"""
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE UNIQUE INDEX uq_ch_localidad_depto_activa
        ON viv_cordoba_hogar (lower(localidad), lower(departamento))
        WHERE deleted_at IS NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_ch_localidad_depto_activa")
