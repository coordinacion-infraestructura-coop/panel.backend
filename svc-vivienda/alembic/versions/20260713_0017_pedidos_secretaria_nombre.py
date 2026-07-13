"""pedidos_secretaria_nombre

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-13
"""
import sqlalchemy as sa
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('viv_cc_pedidos', sa.Column('secretaria', sa.String(100), nullable=True))
    op.add_column('viv_cc_pedidos', sa.Column('created_by_nombre', sa.String(255), nullable=True))
    op.add_column('viv_ch_pedidos', sa.Column('secretaria', sa.String(100), nullable=True))
    op.add_column('viv_ch_pedidos', sa.Column('created_by_nombre', sa.String(255), nullable=True))
    # Backfill existing pedidos as vivienda (all historical pedidos were from vivienda users)
    op.execute("UPDATE viv_cc_pedidos SET secretaria = 'vivienda' WHERE secretaria IS NULL")
    op.execute("UPDATE viv_ch_pedidos SET secretaria = 'vivienda' WHERE secretaria IS NULL")


def downgrade():
    op.drop_column('viv_cc_pedidos', 'created_by_nombre')
    op.drop_column('viv_cc_pedidos', 'secretaria')
    op.drop_column('viv_ch_pedidos', 'created_by_nombre')
    op.drop_column('viv_ch_pedidos', 'secretaria')
