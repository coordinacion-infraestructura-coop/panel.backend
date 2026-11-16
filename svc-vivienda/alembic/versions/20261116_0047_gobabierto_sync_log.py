"""Log de la exportación de pagos de Vivienda a la planilla de Gobierno Abierto

spec-export-gobierno-abierto-vivienda.md §5 · ADR-034. Tabla append-only, una fila por corrida
(mismo patrón que `viv_cc_sync_log`).

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_gobabierto_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("origen", sa.String(20), nullable=False),
    )
    op.create_index("ix_gobabierto_sync_log_started_at", "viv_gobabierto_sync_log", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_gobabierto_sync_log_started_at", table_name="viv_gobabierto_sync_log")
    op.drop_table("viv_gobabierto_sync_log")
