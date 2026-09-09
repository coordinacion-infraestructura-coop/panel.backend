"""estado_hist_y_en_ruta — estados de excepción fuera del camino lineal del stepper

El área técnica marcó que "RECHAZADO por M/C" y "SIN AUTORIZACION MIN.GOB" NO son parte
obligatoria del camino: algunos expedientes pasan por ahí, otros no. Hoy el stepper les pone
✓ a todos los estados anteriores al actual, aunque el expediente nunca haya estado en ellos.

- `viv_checklist_estado_expediente.en_ruta` (BOOLEAN, default TRUE) — FALSE en los 2 de excepción.
- `viv_checklist_estado_hist` — registra cada cambio de "Estado del expediente" para saber si
  el expediente transitó de verdad un estado de excepción.
- Backfill del historial desde `viv_audit_log` (cada PATCH de checklist con `estado_expediente_id`)
  + el estado actual de cada checklist.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-09
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_EXCEPCION_LABELS = ("RECHAZADO por M/C", "SIN AUTORIZACION MIN.GOB")


def upgrade() -> None:
    op.add_column(
        "viv_checklist_estado_expediente",
        sa.Column("en_ruta", sa.Boolean(), server_default="true", nullable=False),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE viv_checklist_estado_expediente SET en_ruta = false WHERE label = ANY(:labels)"
        ),
        {"labels": list(_EXCEPCION_LABELS)},
    )

    op.create_table(
        "viv_checklist_estado_hist",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "checklist_id",
            sa.String(36),
            sa.ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "estado_expediente_id",
            sa.BigInteger(),
            sa.ForeignKey("viv_checklist_estado_expediente.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(200)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_checklist_estado_hist_checklist", "viv_checklist_estado_hist", ["checklist_id"])

    hist_tbl = sa.table(
        "viv_checklist_estado_hist",
        sa.column("id", sa.String()),
        sa.column("checklist_id", sa.String()),
        sa.column("estado_expediente_id", sa.BigInteger()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.String()),
    )

    # 1) Historial reconstruido desde la auditoría (cada PATCH de checklist que tocó el estado).
    filas_audit = conn.execute(
        sa.text(
            """
            SELECT resource_id AS checklist_id,
                   (payload->>'estado_expediente_id')::bigint AS estado_id,
                   created_at, actor_email
            FROM viv_audit_log
            WHERE resource_type = 'checklist_tecnico'
              AND payload ? 'estado_expediente_id'
              AND payload->>'estado_expediente_id' IS NOT NULL
              AND resource_id IN (SELECT id FROM viv_checklist_tecnico)
              AND (payload->>'estado_expediente_id')::bigint
                    IN (SELECT id FROM viv_checklist_estado_expediente)
            ORDER BY created_at
            """
        )
    ).fetchall()
    filas = [
        {
            "id": str(uuid.uuid4()),
            "checklist_id": r.checklist_id,
            "estado_expediente_id": r.estado_id,
            "created_at": r.created_at,
            "created_by": r.actor_email,
        }
        for r in filas_audit
    ]

    # 2) Estado actual de cada checklist (por si no quedó rastro en la auditoría).
    ya = {(f["checklist_id"], f["estado_expediente_id"]) for f in filas}
    actuales = conn.execute(
        sa.text(
            "SELECT id, estado_expediente_id, updated_at, updated_by "
            "FROM viv_checklist_tecnico WHERE estado_expediente_id IS NOT NULL"
        )
    ).fetchall()
    for r in actuales:
        if (r.id, r.estado_expediente_id) not in ya:
            filas.append(
                {
                    "id": str(uuid.uuid4()),
                    "checklist_id": r.id,
                    "estado_expediente_id": r.estado_expediente_id,
                    "created_at": r.updated_at,
                    "created_by": r.updated_by,
                }
            )

    if filas:
        conn.execute(hist_tbl.insert(), filas)


def downgrade() -> None:
    op.drop_index("ix_checklist_estado_hist_checklist", table_name="viv_checklist_estado_hist")
    op.drop_table("viv_checklist_estado_hist")
    op.drop_column("viv_checklist_estado_expediente", "en_ruta")
