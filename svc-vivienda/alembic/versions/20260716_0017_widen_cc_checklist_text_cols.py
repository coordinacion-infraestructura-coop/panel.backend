"""widen_cc_checklist_text_cols — el Sheet puede traer texto libre más largo

El área técnica escribió un valor de 66 caracteres en "REPARTICIÓN"
(columna definida como VARCHAR(50)), lo que hizo fallar el UPDATE con
StringDataRightTruncationError. Estas columnas vienen de celdas de texto
libre del Sheet — no hay garantía real de longitud máxima. Se ensanchan
con margen generoso en vez de intentar acertar un límite "seguro".

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "viv_cc_checklist_tecnico", "estado_expediente",
        type_=sa.String(200), existing_type=sa.String(50),
    )
    op.alter_column(
        "viv_cc_checklist_tecnico", "reparticion",
        type_=sa.String(200), existing_type=sa.String(50),
    )
    op.alter_column(
        "viv_cc_checklist_items", "valor",
        type_=sa.String(200), existing_type=sa.String(50), existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "viv_cc_checklist_items", "valor",
        type_=sa.String(50), existing_type=sa.String(200), existing_nullable=False,
    )
    op.alter_column(
        "viv_cc_checklist_tecnico", "reparticion",
        type_=sa.String(50), existing_type=sa.String(200),
    )
    op.alter_column(
        "viv_cc_checklist_tecnico", "estado_expediente",
        type_=sa.String(50), existing_type=sa.String(200),
    )
