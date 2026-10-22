"""Padrón político de Privada leído por svc-datos-externos (ADR-027)

Lo último que devolvió `GET /internal/privada/padron-politico`: valores actuales y de respaldo
por fila de `priv_localidades_info`. Reemplazo completo, sin `deleted_at` (misma excepción que la
0006 a la 0009). Ver docs/files/spec-padron-politico-gobierno-privada.md §3.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ext_priv_padron_politico",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("departamento", sa.String(120), nullable=False),
        sa.Column("localidad", sa.String(160), nullable=False),
        sa.Column("id_geo", sa.String(30)),
        sa.Column("intendente", sa.String(200)),
        sa.Column("partido", sa.String(200)),
        sa.Column("intendente_respaldo", sa.String(200)),
        sa.Column("partido_respaldo", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ext_priv_padron_politico_id_geo", "ext_priv_padron_politico", ["id_geo"])


def downgrade() -> None:
    op.drop_table("ext_priv_padron_politico")
