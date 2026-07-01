"""cordon cuneta v2 - estructura real del HTML

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("viv_cordon_cuneta")

    op.create_table(
        "viv_cc_estados",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("bg", sa.String(10), nullable=False),
        sa.Column("text_color", sa.String(10), nullable=False),
        sa.Column("orden", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "viv_cordon_cuneta",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("orden", sa.Integer, nullable=False, server_default="0"),
        sa.Column("municipio", sa.String(150), nullable=False),
        sa.Column("departamento", sa.String(100)),
        sa.Column("expediente", sa.String(60)),
        sa.Column("monto", sa.Numeric(18, 2)),
        sa.Column("ok_gob", sa.String(20), nullable=False, server_default="'SI'"),
        sa.Column("doc_exp", sa.Text),
        sa.Column("ejuridico", sa.BigInteger, sa.ForeignKey("viv_cc_estados.id")),
        sa.Column("etecnico", sa.BigInteger, sa.ForeignKey("viv_cc_estados.id")),
        sa.Column("efinanciero", sa.BigInteger, sa.ForeignKey("viv_cc_estados.id")),
        sa.Column("cordon_cuneta_ml", sa.Numeric(10, 2)),
        sa.Column("adoquinado_m2", sa.Numeric(10, 2)),
        sa.Column("obs", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(200)),
    )
    op.create_index("ix_cc_orden", "viv_cordon_cuneta", ["orden"])

    op.create_table(
        "viv_cc_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("presupuesto", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("viv_cc_config")
    op.drop_table("viv_cordon_cuneta")
    op.drop_table("viv_cc_estados")
    op.create_table(
        "viv_cordon_cuneta",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("municipio", sa.String(150), nullable=False),
        sa.Column("departamento", sa.String(100)),
        sa.Column("numero_expediente", sa.String(50)),
        sa.Column("monto", sa.Numeric(16, 2)),
        sa.Column("cordon_cuneta_ml", sa.Numeric(10, 2)),
        sa.Column("adoquinado_m2", sa.Numeric(10, 2)),
        sa.Column("est_documentacion", sa.String(100)),
        sa.Column("est_juridico_adm", sa.String(100)),
        sa.Column("est_tecnico", sa.String(100)),
        sa.Column("est_presup_fin", sa.String(100)),
        sa.Column("ok_ministerio", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("observaciones", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(200)),
    )
