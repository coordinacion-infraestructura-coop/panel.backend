"""obs_obra_bitacora — "Observaciones de obra" pasa de campo único a bitácora fechada

El área técnica pidió que las observaciones de obra funcionen como las del expediente:
una entrada por fecha, con el usuario que la cargó, y un botón "Guardar" explícito
(spec v1.3.0 — se acepta el botón aunque el patrón general del módulo sea autosave).

- Nueva tabla `viv_checklist_obra_obs` (misma forma que `viv_*_pedidos`).
- El valor actual de `viv_checklist_tecnico.obs_obra` (si lo hay) se migra a una entrada.
- Se elimina la columna `viv_checklist_tecnico.obs_obra`.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-08
"""
from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_checklist_obra_obs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "checklist_id",
            sa.String(36),
            sa.ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(200)),
        sa.Column("created_by_nombre", sa.String(255)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_checklist_obra_obs_checklist", "viv_checklist_obra_obs", ["checklist_id"])

    conn = op.get_bind()
    filas = conn.execute(
        sa.text(
            "SELECT id, obs_obra, updated_by, updated_at FROM viv_checklist_tecnico "
            "WHERE obs_obra IS NOT NULL AND btrim(obs_obra) <> ''"
        )
    ).fetchall()
    obs_tbl = sa.table(
        "viv_checklist_obra_obs",
        sa.column("id", sa.String()),
        sa.column("checklist_id", sa.String()),
        sa.column("descripcion", sa.Text()),
        sa.column("fecha", sa.Date()),
        sa.column("created_by", sa.String()),
    )
    nuevas = [
        {
            "id": str(uuid.uuid4()),
            "checklist_id": row.id,
            "descripcion": row.obs_obra,
            "fecha": row.updated_at.date() if row.updated_at is not None else date.today(),
            "created_by": row.updated_by,
        }
        for row in filas
    ]
    if nuevas:
        conn.execute(obs_tbl.insert(), nuevas)

    op.drop_column("viv_checklist_tecnico", "obs_obra")


def downgrade() -> None:
    op.add_column("viv_checklist_tecnico", sa.Column("obs_obra", sa.Text(), nullable=True))
    conn = op.get_bind()
    # Restaura la última observación (por fecha) de cada checklist en el campo único.
    conn.execute(
        sa.text(
            """
            UPDATE viv_checklist_tecnico t SET obs_obra = sub.descripcion
            FROM (
                SELECT DISTINCT ON (checklist_id) checklist_id, descripcion
                FROM viv_checklist_obra_obs
                ORDER BY checklist_id, fecha DESC, created_at DESC
            ) sub
            WHERE sub.checklist_id = t.id
            """
        )
    )
    op.drop_index("ix_checklist_obra_obs_checklist", table_name="viv_checklist_obra_obs")
    op.drop_table("viv_checklist_obra_obs")
