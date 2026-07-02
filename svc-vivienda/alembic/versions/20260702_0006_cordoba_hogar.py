"""cordoba_hogar — tablas viv_ch_estados, viv_cordoba_hogar, viv_ch_config, viv_ch_pedidos

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_ch_estados",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("bg", sa.String(10), nullable=False),
        sa.Column("text_color", sa.String(10), nullable=False),
        sa.Column("orden", sa.Integer, nullable=False),
    )

    op.create_table(
        "viv_cordoba_hogar",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("orden", sa.Integer, nullable=False),
        sa.Column("localidad", sa.String(150), nullable=False),
        sa.Column("departamento", sa.String(100)),
        sa.Column("fecha_anuncio", sa.Date),
        sa.Column("expediente", sa.String(60)),
        sa.Column("monto", sa.Numeric(18, 2)),
        sa.Column("cantidad_casas", sa.Integer),
        sa.Column("ok_gob", sa.String(20), nullable=False, server_default="SI"),
        sa.Column("doc_exp", sa.Text),
        sa.Column("ejuridico", sa.BigInteger, sa.ForeignKey("viv_ch_estados.id")),
        sa.Column("etecnico", sa.BigInteger, sa.ForeignKey("viv_ch_estados.id")),
        sa.Column("efinanciero", sa.BigInteger, sa.ForeignKey("viv_ch_estados.id")),
        sa.Column("obs", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255)),
    )

    op.create_table(
        "viv_ch_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("presupuesto", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "viv_ch_pedidos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "localidad_id",
            sa.String(36),
            sa.ForeignKey("viv_cordoba_hogar.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("descripcion", sa.Text, nullable=False),
        sa.Column("fecha_pedido", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255)),
    )


def downgrade() -> None:
    op.drop_table("viv_ch_pedidos")
    op.drop_table("viv_ch_config")
    op.drop_table("viv_cordoba_hogar")
    op.drop_table("viv_ch_estados")
