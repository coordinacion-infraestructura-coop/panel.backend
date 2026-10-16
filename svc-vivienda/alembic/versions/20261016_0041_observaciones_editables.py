"""Corrección de observaciones: marca de edición en las bitácoras del Checklist Técnico

docs/files/spec-checklist-tecnico-dgv.md v1.7.0 §6-ter.2. Suma `editado_at`, `editado_por` y
`editado_por_nombre` (todas NULL) a las observaciones del expediente (`viv_cc_pedidos`,
`viv_ch_pedidos`, `viv_ml_pedidos`) y a las de obra (`viv_checklist_obra_obs`). No toca datos:
una fila sin corregir queda con las tres en NULL.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

_TABLAS = ("viv_cc_pedidos", "viv_ch_pedidos", "viv_ml_pedidos", "viv_checklist_obra_obs")


def upgrade() -> None:
    for tabla in _TABLAS:
        op.add_column(tabla, sa.Column("editado_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(tabla, sa.Column("editado_por", sa.String(200), nullable=True))
        op.add_column(tabla, sa.Column("editado_por_nombre", sa.String(255), nullable=True))


def downgrade() -> None:
    for tabla in _TABLAS:
        op.drop_column(tabla, "editado_por_nombre")
        op.drop_column(tabla, "editado_por")
        op.drop_column(tabla, "editado_at")
