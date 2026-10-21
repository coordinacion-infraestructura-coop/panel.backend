"""ATP Interno de Gobierno: pagos y log de corridas

docs/files/spec-atp-interno.md §2

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "atp_interno_pagos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("anio_planilla", sa.Integer, nullable=False),
        sa.Column("fila", sa.Integer, nullable=False),
        sa.Column("codigo_indec", sa.String(6), nullable=False),
        sa.Column("localidad", sa.String(150)),
        sa.Column("departamento", sa.String(100)),
        sa.Column("fecha", sa.Date),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("referente", sa.String(120)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_atp_interno_pagos_anio_planilla", "atp_interno_pagos", ["anio_planilla"])
    op.create_index("ix_atp_interno_anio_codigo", "atp_interno_pagos", ["anio", "codigo_indec"])
    op.create_table(
        "atp_interno_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("anio_planilla", sa.Integer),
        sa.Column("filas_leidas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_cargadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_descartadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("anomalias", sa.Text),
        sa.Column("mensaje", sa.Text),
        sa.Column("triggered_by", sa.String(50)),
    )


def downgrade() -> None:
    op.drop_table("atp_interno_sync_log")
    op.drop_index("ix_atp_interno_anio_codigo", table_name="atp_interno_pagos")
    op.drop_index("ix_atp_interno_pagos_anio_planilla", table_name="atp_interno_pagos")
    op.drop_table("atp_interno_pagos")
