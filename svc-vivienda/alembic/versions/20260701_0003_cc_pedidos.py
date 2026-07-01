"""viv_cc_pedidos — historial de comunicaciones por municipio

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_cc_pedidos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("municipio_id", sa.String(36), sa.ForeignKey("viv_cordon_cuneta.id", ondelete="CASCADE"), nullable=False),
        sa.Column("descripcion", sa.Text, nullable=False),
        sa.Column("fecha_pedido", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(200)),
    )
    op.create_index("ix_cc_pedidos_municipio", "viv_cc_pedidos", ["municipio_id"])


def downgrade() -> None:
    op.drop_index("ix_cc_pedidos_municipio", "viv_cc_pedidos")
    op.drop_table("viv_cc_pedidos")
