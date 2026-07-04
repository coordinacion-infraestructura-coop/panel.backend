"""estado_general + deleted_at + historial + geo_localidades — schema

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- dimension flags on CC estados ---
    op.add_column("viv_cc_estados", sa.Column("aplica_juridico", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("viv_cc_estados", sa.Column("aplica_tecnico", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("viv_cc_estados", sa.Column("aplica_financiero", sa.Boolean, nullable=False, server_default="true"))

    # --- dimension flags on CH estados ---
    op.add_column("viv_ch_estados", sa.Column("aplica_juridico", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("viv_ch_estados", sa.Column("aplica_tecnico", sa.Boolean, nullable=False, server_default="true"))
    op.add_column("viv_ch_estados", sa.Column("aplica_financiero", sa.Boolean, nullable=False, server_default="true"))

    # --- estado_general + deleted_at on CC municipios ---
    op.add_column("viv_cordon_cuneta", sa.Column("estado_general", sa.BigInteger, nullable=True))
    op.add_column("viv_cordon_cuneta", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_cc_estado_general", "viv_cordon_cuneta", "viv_cc_estados",
        ["estado_general"], ["id"]
    )

    # --- estado_general + deleted_at on CH localidades ---
    op.add_column("viv_cordoba_hogar", sa.Column("estado_general", sa.BigInteger, nullable=True))
    op.add_column("viv_cordoba_hogar", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_ch_estado_general", "viv_cordoba_hogar", "viv_ch_estados",
        ["estado_general"], ["id"]
    )

    # --- CC estado historial ---
    op.create_table(
        "viv_cc_estado_historial",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("municipio_id", sa.String(36), sa.ForeignKey("viv_cordon_cuneta.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campo", sa.String(30), nullable=False),
        sa.Column("estado_anterior_id", sa.BigInteger, sa.ForeignKey("viv_cc_estados.id"), nullable=True),
        sa.Column("estado_nuevo_id", sa.BigInteger, sa.ForeignKey("viv_cc_estados.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
    )

    # --- CH estado historial ---
    op.create_table(
        "viv_ch_estado_historial",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("localidad_id", sa.String(36), sa.ForeignKey("viv_cordoba_hogar.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campo", sa.String(30), nullable=False),
        sa.Column("estado_anterior_id", sa.BigInteger, sa.ForeignKey("viv_ch_estados.id"), nullable=True),
        sa.Column("estado_nuevo_id", sa.BigInteger, sa.ForeignKey("viv_ch_estados.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
    )

    # --- geo localidades ---
    op.create_table(
        "viv_geo_localidades",
        sa.Column("id_geo", sa.String(20), primary_key=True),
        sa.Column("departamento", sa.String(100), nullable=False),
        sa.Column("localidad", sa.String(150), nullable=False),
        sa.Column("lat_centro", sa.Numeric(10, 7), nullable=True),
        sa.Column("lon_centro", sa.Numeric(10, 7), nullable=True),
        sa.Column("activo", sa.Boolean, nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("viv_geo_localidades")
    op.drop_table("viv_ch_estado_historial")
    op.drop_table("viv_cc_estado_historial")
    op.drop_constraint("fk_ch_estado_general", "viv_cordoba_hogar", type_="foreignkey")
    op.drop_column("viv_cordoba_hogar", "deleted_at")
    op.drop_column("viv_cordoba_hogar", "estado_general")
    op.drop_constraint("fk_cc_estado_general", "viv_cordon_cuneta", type_="foreignkey")
    op.drop_column("viv_cordon_cuneta", "deleted_at")
    op.drop_column("viv_cordon_cuneta", "estado_general")
    op.drop_column("viv_ch_estados", "aplica_financiero")
    op.drop_column("viv_ch_estados", "aplica_tecnico")
    op.drop_column("viv_ch_estados", "aplica_juridico")
    op.drop_column("viv_cc_estados", "aplica_financiero")
    op.drop_column("viv_cc_estados", "aplica_tecnico")
    op.drop_column("viv_cc_estados", "aplica_juridico")
