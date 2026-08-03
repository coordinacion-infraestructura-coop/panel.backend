"""informe_snapshot — cache de informes calculados por programa (CC, CH)

Tabla genérica: cada fila es una corrida de cálculo del informe de un programa,
identificada por `programa`. No se sobreescribe (igual criterio que
viv_cc_sync_log) — se guarda historial completo y se lee la última por
(programa, computed_at DESC). El botón "Actualizar informe" del frontend
dispara una corrida nueva; la carga normal de la página lee la última.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_informe_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("programa", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_by", sa.String(255)),
        sa.Column("duracion_ms", sa.Integer),
    )
    op.create_index(
        "ix_informe_snapshot_programa_fecha",
        "viv_informe_snapshot",
        ["programa", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_informe_snapshot_programa_fecha", table_name="viv_informe_snapshot")
    op.drop_table("viv_informe_snapshot")
