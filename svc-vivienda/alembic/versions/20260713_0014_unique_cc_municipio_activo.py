"""unique_cc_municipio_activo

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-13
"""
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE UNIQUE INDEX uq_cc_municipio_depto_activo
        ON viv_cordon_cuneta (lower(municipio), lower(departamento))
        WHERE deleted_at IS NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_cc_municipio_depto_activo")
