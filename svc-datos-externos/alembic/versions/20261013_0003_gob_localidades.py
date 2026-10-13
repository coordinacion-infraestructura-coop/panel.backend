"""Nomenclador de Gobierno + ficha de localidad: ext_gob_localidades, ext_gob_entes, ext_gob_sync_log

Ver docs/files/spec-datos-externos-fase1-nomenclador-demografia.md §4.

Sólo esquema: los datos los carga el sync
(`POST /internal/datos-externos/gobierno/localidades/sync`).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ext_gob_localidades",
        sa.Column("codigo_indec", sa.String(20), primary_key=True),
        sa.Column("nombre_gob", sa.String(150), nullable=False),
        sa.Column("departamento_gob", sa.String(100), nullable=False),
        sa.Column("codigo_dpto_indec", sa.String(10)),
        sa.Column("id_copa", sa.Integer),
        sa.Column("tipo", sa.String(2)),
        sa.Column("id_geo", sa.String(20)),
        sa.Column("match_tipo", sa.String(20)),
        # Públicos
        sa.Column("superficie_km2", sa.Numeric(12, 4)),
        sa.Column("poblacion_2010", sa.Integer),
        sa.Column("poblacion_2022_gob", sa.Integer),
        # Restringidos (sólo rol Autoridad)
        sa.Column("electores", sa.Integer),
        sa.Column("empleados", sa.Integer),
        sa.Column("masa_salarial", sa.Numeric(18, 2)),
        sa.Column("intendente", sa.String(150)),
        sa.Column("reelecto", sa.Boolean),
        sa.Column("partido", sa.String(150)),
        sa.Column("continuidad", sa.Boolean),
        sa.Column("legislador", sa.String(150)),
        sa.Column("partido_legislador", sa.String(150)),
        sa.Column("contacto_intendente", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("id_copa", name="uq_ext_gob_localidades_id_copa"),
    )
    op.create_index("ix_ext_gob_localidades_id_geo", "ext_gob_localidades", ["id_geo"])

    op.create_table(
        "ext_gob_entes",
        sa.Column("codigo", sa.String(20), primary_key=True),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("tipo_ente", sa.String(20), nullable=False),
        sa.Column("departamento", sa.String(100)),
        sa.Column("poblacion_2022", sa.Integer),
        sa.Column("poblacion_2010", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "ext_gob_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fuente", sa.String(40), nullable=False),
        sa.Column("filas_leidas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_upsert", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_error", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_sin_match", sa.Integer, nullable=False, server_default="0"),
        sa.Column("anomalias", sa.JSON),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("corrida_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("disparado_por", sa.String(80)),
    )
    op.create_index("ix_ext_gob_sync_log_fuente_corrida", "ext_gob_sync_log", ["fuente", "corrida_en"])


def downgrade() -> None:
    op.drop_index("ix_ext_gob_sync_log_fuente_corrida", table_name="ext_gob_sync_log")
    op.drop_table("ext_gob_sync_log")
    op.drop_table("ext_gob_entes")
    op.drop_index("ix_ext_gob_localidades_id_geo", table_name="ext_gob_localidades")
    op.drop_table("ext_gob_localidades")
