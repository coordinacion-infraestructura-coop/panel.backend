"""Esquema inicial: ext_geo_censo, ext_transferencias, ext_transferencias_sync_log

Ver docs/files/spec-resumen-territorial-tablero-v2.md §2.2 (ADR-025).

Revision ID: 0001
Revises:
Create Date: 2026-09-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ext_geo_censo",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("id_geo", sa.String(20)),
        sa.Column("codigo_indec", sa.String(20), nullable=False, unique=True),
        sa.Column("categoria", sa.String(2), nullable=False),
        sa.Column("departamento_censo", sa.String(100)),
        sa.Column("localidad_censo", sa.String(150), nullable=False),
        sa.Column("poblacion_2022", sa.Integer),
        sa.Column("viviendas_2022", sa.Integer),
        sa.Column("match_tipo", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ext_geo_censo_id_geo", "ext_geo_censo", ["id_geo"])

    op.create_table(
        "ext_transferencias",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("periodo", sa.Date, nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("id_geo", sa.String(20)),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("nombre_pdf", sa.String(200), nullable=False),
        sa.Column("departamento_pdf", sa.String(100), nullable=False),
        sa.Column("concepto", sa.String(50), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("match_tipo", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("periodo", "tipo", "nombre_pdf", "concepto", name="uq_ext_transferencias_natural"),
    )
    op.create_index("ix_ext_transferencias_id_geo", "ext_transferencias", ["id_geo"])
    op.create_index("ix_ext_transferencias_periodo", "ext_transferencias", ["periodo"])

    op.create_table(
        "ext_transferencias_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("periodo", sa.Date, nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("filas_procesadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_sin_match", sa.Integer, nullable=False, server_default="0"),
        sa.Column("anomalias", sa.JSON),
        sa.Column("corrida_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("disparado_por", sa.String(80)),
    )


def downgrade() -> None:
    op.drop_table("ext_transferencias_sync_log")
    op.drop_table("ext_transferencias")
    op.drop_table("ext_geo_censo")
