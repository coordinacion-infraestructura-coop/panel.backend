"""cc_checklist_tecnico — tablas de sincronizacion del Google Sheet "Base TOTAL"

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_cc_checklist_tecnico",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("localidad", sa.String(150), nullable=False),
        sa.Column("departamento", sa.String(100)),
        sa.Column("expediente", sa.String(60)),
        sa.Column("orden_sheet", sa.Integer),
        sa.Column("tipo", sa.String(1)),
        sa.Column("intendente", sa.String(200)),
        sa.Column("telefono", sa.String(60)),
        sa.Column("email", sa.String(200)),
        sa.Column("contacto_tecnico", sa.String(300)),
        sa.Column("monto_convenio", sa.Numeric(18, 2)),
        sa.Column("cordon_cuneta_ml", sa.Numeric(10, 2)),
        sa.Column("adoquinado_m2", sa.Numeric(10, 2)),
        sa.Column("estado_expediente", sa.String(50)),
        sa.Column("observaciones", sa.Text),
        sa.Column("fecha_radicacion", sa.Date),
        sa.Column("reparticion", sa.String(50)),
        sa.Column(
            "municipio_id",
            sa.String(36),
            sa.ForeignKey("viv_cordon_cuneta.id"),
            nullable=True,
        ),
        sa.Column("sheet_row_number", sa.Integer, nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.execute("""
        CREATE UNIQUE INDEX uq_cc_checklist_localidad_depto
        ON viv_cc_checklist_tecnico (lower(trim(localidad)), lower(trim(coalesce(departamento, ''))))
    """)
    op.create_index(
        "ix_cc_checklist_municipio", "viv_cc_checklist_tecnico", ["municipio_id"]
    )

    op.create_table(
        "viv_cc_checklist_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "checklist_id",
            sa.String(36),
            sa.ForeignKey("viv_cc_checklist_tecnico.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_num", sa.SmallInteger, nullable=False),
        sa.Column("item_label", sa.String(150), nullable=False),
        sa.Column("valor", sa.String(50), nullable=False),
        sa.UniqueConstraint("checklist_id", "item_num", name="uq_cc_checklist_item"),
    )

    op.create_table(
        "viv_cc_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("filas_leidas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_insertadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_actualizadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_error", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errores", sa.Text),
        sa.Column("triggered_by", sa.String(50)),
    )


def downgrade() -> None:
    op.drop_table("viv_cc_sync_log")
    op.drop_table("viv_cc_checklist_items")
    op.drop_index("ix_cc_checklist_municipio", table_name="viv_cc_checklist_tecnico")
    op.execute("DROP INDEX IF EXISTS uq_cc_checklist_localidad_depto")
    op.drop_table("viv_cc_checklist_tecnico")
