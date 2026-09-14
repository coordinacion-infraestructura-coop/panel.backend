"""vinculación vivienda -> privada — viv_privada_vinculos + viv_privada_sync_log

Snapshot (`viv_privada_vinculos`, 1 fila por caso CC/CH/ML, upsert) + log
append-only (`viv_privada_sync_log`, 1 fila por intento de sync) para la
vinculación automática de casos de Vivienda con gestiones de Privada (ADR-020).
`(caso_tipo, caso_id)` sin FK real — polimórfico, mismo patrón que
`viv_checklist_tecnico` (`programa`/`entidad_id`).

Spec: docs/files/spec-vinculacion-vivienda-privada.md

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_privada_vinculos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("caso_tipo", sa.String(2), nullable=False),
        sa.Column("caso_id", sa.String(36), nullable=False),
        sa.Column("id_legacy", sa.String(100), nullable=False, unique=True),
        sa.Column("gestion_id", sa.String(36)),
        sa.Column("estado_vinculo", sa.String(20), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("motivo", sa.String(60)),
        sa.Column("ultimo_intento_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_ok_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("caso_tipo", "caso_id", name="uq_privada_vinculo_caso"),
        sa.CheckConstraint("caso_tipo IN ('cc','ch','ml')", name="ck_privada_vinculo_caso_tipo"),
        sa.CheckConstraint(
            "estado_vinculo IN ('LINKED','PENDING_REVIEW','ERROR')", name="ck_privada_vinculo_estado"
        ),
    )

    op.create_table(
        "viv_privada_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("caso_tipo", sa.String(2), nullable=False),
        sa.Column("caso_id", sa.String(36), nullable=False),
        sa.Column("id_legacy", sa.String(100), nullable=False),
        sa.Column("resultado", sa.String(20), nullable=False),
        sa.Column("gestion_id", sa.String(36)),
        sa.Column("motivo", sa.String(60)),
        sa.Column("diff_json", sa.JSON),
        sa.Column("http_status", sa.Integer),
        sa.Column("error_detalle", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_privada_sync_log_caso", "viv_privada_sync_log", ["caso_tipo", "caso_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_privada_sync_log_caso", table_name="viv_privada_sync_log")
    op.drop_table("viv_privada_sync_log")
    op.drop_table("viv_privada_vinculos")
