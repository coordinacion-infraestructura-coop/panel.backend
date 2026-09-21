"""atp sync — espejo de solo lectura de la hoja "BD" del Sheet
"ATP - Compromiso Gobernador"

Fase 0 de svc-gralgob (ver docs/files/spec-sync-atp-compromiso-gobernador.md):
solo las tablas del sync, sin módulo de negocio. Alcance: compromisos ATP
(Aporte del Tesoro Provincial) + cronograma de pago mensual normalizado.

Revision ID: 0001
Revises:
Create Date: 2026-09-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "atp_compromisos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sheet_row_number", sa.Integer, nullable=False, unique=True),
        sa.Column("departamento", sa.String(100)),
        sa.Column("localidad", sa.String(150)),
        sa.Column("ministerio_destino", sa.String(100)),
        sa.Column("fecha_anuncio", sa.Date),
        sa.Column("nro_expediente", sa.String(60)),
        sa.Column("derivado", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("monto", sa.Numeric(18, 2)),
        sa.Column("destino", sa.Text),
        sa.Column("saldo_atp", sa.Numeric(18, 2)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "atp_cronograma_pagos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "compromiso_id", sa.String(36),
            sa.ForeignKey("atp_compromisos.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("periodo", sa.Date, nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint("compromiso_id", "periodo", name="uq_atp_cronograma_compromiso_periodo"),
    )

    op.create_table(
        "atp_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("filas_leidas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_insertadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_actualizadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_error", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errores", sa.Text),
        sa.Column("triggered_by", sa.String(50)),
    )


def downgrade() -> None:
    op.drop_table("atp_sync_log")
    op.drop_table("atp_cronograma_pagos")
    op.drop_table("atp_compromisos")
