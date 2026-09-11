"""notificaciones — feed interno de alertas del sistema

Panel de notificaciones internas (transversal, montado en /api/v1/notificaciones,
mismo criterio que app/portal/ — ADR-007 / ADR-019). Feed global en
`portal_notificaciones`; el estado de lectura es por usuario en
`portal_notificacion_lecturas`. Se siembran 2 filas de ejemplo para que el panel
no arranque vacío.

Spec: docs/files/spec-notificaciones.md

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-10
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_notificaciones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("titulo", sa.String(200), nullable=False),
        sa.Column("mensaje", sa.Text, nullable=False),
        sa.Column("nivel", sa.String(20), nullable=False, server_default="info"),
        sa.Column("origen", sa.String(60), nullable=False, server_default="sistema"),
        sa.Column("enlace", sa.String(500)),
        sa.Column("destino_tipo", sa.String(20), nullable=False, server_default="global"),
        sa.Column("destino_valor", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(200)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "nivel IN ('info','exito','advertencia','error')", name="ck_notif_nivel"
        ),
        sa.CheckConstraint(
            "destino_tipo IN ('global','rol','secretaria')", name="ck_notif_destino_tipo"
        ),
    )
    op.create_index(
        "ix_portal_notificaciones_created_at", "portal_notificaciones", ["created_at"]
    )

    op.create_table(
        "portal_notificacion_lecturas",
        sa.Column(
            "notificacion_id",
            sa.String(36),
            sa.ForeignKey("portal_notificaciones.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("usuario_email", sa.String(200), primary_key=True),
        sa.Column("leida_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_portal_notif_lecturas_usuario", "portal_notificacion_lecturas", ["usuario_email"]
    )

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table(
            "portal_notificaciones",
            sa.column("id", sa.String),
            sa.column("titulo", sa.String),
            sa.column("mensaje", sa.Text),
            sa.column("nivel", sa.String),
            sa.column("origen", sa.String),
            sa.column("enlace", sa.String),
            sa.column("destino_tipo", sa.String),
            sa.column("destino_valor", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("created_by", sa.String),
        ),
        [
            {
                "id": str(uuid.uuid4()),
                "titulo": "Panel de notificaciones activo",
                "mensaje": "Desde acá vas a ver las alertas internas del sistema.",
                "nivel": "info",
                "origen": "sistema",
                "enlace": None,
                "destino_tipo": "global",
                "destino_valor": None,
                "created_at": now,
                "created_by": "migracion-0028",
            },
            {
                "id": str(uuid.uuid4()),
                "titulo": "Ejemplo de alerta operativa",
                "mensaje": (
                    "Los fallos de sincronización y los avisos del sistema van a "
                    "aparecer con este formato."
                ),
                "nivel": "advertencia",
                "origen": "sync-checklist",
                "enlace": None,
                "destino_tipo": "global",
                "destino_valor": None,
                "created_at": now,
                "created_by": "migracion-0028",
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portal_notif_lecturas_usuario", table_name="portal_notificacion_lecturas"
    )
    op.drop_table("portal_notificacion_lecturas")
    op.drop_index(
        "ix_portal_notificaciones_created_at", table_name="portal_notificaciones"
    )
    op.drop_table("portal_notificaciones")
