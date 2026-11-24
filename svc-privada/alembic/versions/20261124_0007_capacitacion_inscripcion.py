"""priv_capacitacion_inscripcion — espejo de las respuestas del formulario de inscripción

docs/files/spec-privada-sync-capacitacion.md §6. El correo no se guarda: solo su SHA-256.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "priv_capacitacion_inscripcion",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("capacitacion", sa.String(60), nullable=False),
        sa.Column("fila_origen", sa.Integer, nullable=False),
        sa.Column("marca_temporal", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("apellido", sa.String(120)),
        sa.Column("nombre", sa.String(120)),
        sa.Column("cargo", sa.String(60)),
        sa.Column("localidad_texto", sa.String(200)),
        sa.Column("departamento_texto", sa.String(120)),
        sa.Column("id_geo", sa.String(30)),
        sa.Column("match_tipo", sa.String(20), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("capacitacion", "marca_temporal", "email_hash", name="uq_priv_capacitacion_inscripcion"),
    )
    op.create_index("ix_priv_capacitacion_inscripcion_capacitacion", "priv_capacitacion_inscripcion", ["capacitacion"])


def downgrade() -> None:
    op.drop_index("ix_priv_capacitacion_inscripcion_capacitacion", table_name="priv_capacitacion_inscripcion")
    op.drop_table("priv_capacitacion_inscripcion")
