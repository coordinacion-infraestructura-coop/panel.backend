"""resumen_territorial_snapshot — cache del Resumen Territorial consolidado

Una fila por corrida de cálculo del panel consolidado por localidad/departamento
(Vivienda: CC/CH/ML + Secretaría Privada). No se sobreescribe — se lee la última
por computed_at DESC (mismo criterio que viv_informe_snapshot). El payload guarda
el resumen COMPLETO; el filtro por área/rol se aplica en el GET.

Spec: docs/files/spec-resumen-territorial.md §5.1

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_resumen_territorial_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_by", sa.String(255)),
        sa.Column("duracion_ms", sa.Integer),
    )
    op.create_index(
        "ix_resumen_territorial_snapshot_fecha",
        "viv_resumen_territorial_snapshot",
        ["computed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_resumen_territorial_snapshot_fecha",
        table_name="viv_resumen_territorial_snapshot",
    )
    op.drop_table("viv_resumen_territorial_snapshot")
