"""Checklist Técnico v1.6.0: avance de obra, fecha de fin de obra y estado "No Aplica"

docs/files/spec-checklist-tecnico-dgv.md v1.6.0 (pedidos del área de Vivienda, 2026-10-02).

1. `viv_checklist_avance_medicion`: historial de mediciones de avance físico de obra
   (fecha + % 0..100 + usuario, soft delete).
2. `viv_checklist_tecnico.fecha_fin_obra`: fecha de finalización al 100%, manual.
3. `viv_checklist_item_estado.excluye_completitud` + fila "No Proyectado / No Aplica",
   con `orden` = máximo + 1 para que nunca sea el estado por defecto de un ítem nuevo.
   CHECK: un estado no puede ser `es_completo` y `excluye_completitud` a la vez.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_NO_APLICA_LABEL = "No Proyectado / No Aplica"


def upgrade() -> None:
    # ── 1. Historial de avance ───────────────────────────────────────────────
    op.create_table(
        "viv_checklist_avance_medicion",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "checklist_id",
            sa.String(36),
            sa.ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fecha_medicion", sa.Date(), nullable=False),
        sa.Column("porcentaje", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.Column("created_by_nombre", sa.String(255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("porcentaje BETWEEN 0 AND 100", name="ck_avance_porcentaje_rango"),
    )
    op.create_index(
        "ix_viv_checklist_avance_medicion_checklist_id",
        "viv_checklist_avance_medicion",
        ["checklist_id"],
    )

    # ── 2. Fecha de fin de obra ──────────────────────────────────────────────
    op.add_column("viv_checklist_tecnico", sa.Column("fecha_fin_obra", sa.Date(), nullable=True))

    # ── 3. Estado "No Proyectado / No Aplica" ────────────────────────────────
    op.add_column(
        "viv_checklist_item_estado",
        sa.Column("excluye_completitud", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_check_constraint(
        "ck_item_estado_flags_excluyentes",
        "viv_checklist_item_estado",
        "NOT (es_completo AND excluye_completitud)",
    )
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO viv_checklist_item_estado
                (id, label, orden, activo, bg, text_color, es_completo, excluye_completitud)
            SELECT COALESCE(MAX(id), 0) + 1, :label, COALESCE(MAX(orden), 0) + 1, true,
                   '#e2e8f0', '#475569', false, true
            FROM viv_checklist_item_estado
            """
        ),
        {"label": _NO_APLICA_LABEL},
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Los ítems en un estado "no aplica" vuelven al estado por defecto (activo de menor orden).
    conn.execute(
        sa.text(
            """
            UPDATE viv_checklist_items
            SET item_estado_id = (
                SELECT id FROM viv_checklist_item_estado
                WHERE activo AND NOT excluye_completitud
                ORDER BY orden, id LIMIT 1
            )
            WHERE item_estado_id IN (
                SELECT id FROM viv_checklist_item_estado WHERE excluye_completitud
            )
            """
        )
    )
    conn.execute(
        sa.text("DELETE FROM viv_checklist_item_estado WHERE label = :label AND excluye_completitud"),
        {"label": _NO_APLICA_LABEL},
    )
    op.drop_constraint("ck_item_estado_flags_excluyentes", "viv_checklist_item_estado", type_="check")
    op.drop_column("viv_checklist_item_estado", "excluye_completitud")
    op.drop_column("viv_checklist_tecnico", "fecha_fin_obra")
    op.drop_index("ix_viv_checklist_avance_medicion_checklist_id", "viv_checklist_avance_medicion")
    op.drop_table("viv_checklist_avance_medicion")
