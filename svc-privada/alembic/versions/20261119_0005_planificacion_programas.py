"""priv_plan_* — planificación de programas por localidad (ADR-036)

docs/files/spec-privada-planificacion-programas.md §4. Catálogo de programas, prioridades,
estados y columnas por programa, planilla por (programa, localidad) e historial visible.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _auditoria() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.String(200)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    ]


def _catalogo(nombre: str, *extra: sa.Column) -> None:
    op.create_table(
        nombre,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("programa_id", sa.Integer, sa.ForeignKey("priv_plan_programas.id"), nullable=False),
        *extra,
        sa.Column("orden", sa.Integer, nullable=False, server_default="0"),
        *_auditoria(),
    )
    op.create_index(f"ix_{nombre}_programa_id", nombre, ["programa_id"])


def upgrade() -> None:
    op.create_table(
        "priv_plan_programas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("area", sa.String(40), nullable=False),
        sa.Column("fuente", sa.String(40)),
        sa.Column("descripcion", sa.Text),
        sa.Column("orden", sa.Integer, nullable=False, server_default="0"),
        sa.Column("activo", sa.Boolean, nullable=False, server_default="true"),
        *_auditoria(),
    )
    op.create_index(
        "uq_priv_plan_programas_nombre", "priv_plan_programas", [sa.text("lower(nombre)")],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    _catalogo(
        "priv_plan_estados",
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("color_bg", sa.String(9)),
        sa.Column("color_texto", sa.String(9)),
    )
    _catalogo(
        "priv_plan_prioridades",
        sa.Column("codigo", sa.String(10), nullable=False),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("color_bg", sa.String(9)),
        sa.Column("color_texto", sa.String(9)),
        sa.Column("excluye", sa.Boolean, nullable=False, server_default="false"),
    )
    _catalogo(
        "priv_plan_columnas",
        sa.Column("clave", sa.String(60), nullable=False),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("opciones", JSONB),
        sa.Column("visible", sa.Boolean, nullable=False, server_default="true"),
    )
    # La clave es estable para siempre (también la de columnas borradas: sus datos siguen en `valores`).
    op.create_unique_constraint("uq_priv_plan_columnas_clave", "priv_plan_columnas", ["programa_id", "clave"])

    op.create_table(
        "priv_plan_localidad",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("programa_id", sa.Integer, sa.ForeignKey("priv_plan_programas.id"), nullable=False),
        sa.Column("id_geo", sa.String(30), sa.ForeignKey("priv_geo_localidades.id_geo"), nullable=False),
        sa.Column("prioridad_id", sa.Integer, sa.ForeignKey("priv_plan_prioridades.id")),
        sa.Column("estado_id", sa.Integer, sa.ForeignKey("priv_plan_estados.id")),
        sa.Column("ok_gobernador", sa.Boolean),
        sa.Column("valores", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_auditoria(),
    )
    op.create_index("ix_priv_plan_localidad_programa_id", "priv_plan_localidad", ["programa_id"])
    op.create_index(
        "uq_priv_plan_localidad_programa_geo", "priv_plan_localidad", ["programa_id", "id_geo"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "priv_plan_historial",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("programa_id", sa.Integer, sa.ForeignKey("priv_plan_programas.id"), nullable=False),
        sa.Column("id_geo", sa.String(30), nullable=False),
        sa.Column("campo", sa.String(80), nullable=False),
        sa.Column("valor_anterior", sa.Text),
        sa.Column("valor_nuevo", sa.Text),
        sa.Column("usuario", sa.String(200)),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_priv_plan_historial_programa_geo", "priv_plan_historial", ["programa_id", "id_geo"])


def downgrade() -> None:
    op.drop_table("priv_plan_historial")
    op.drop_table("priv_plan_localidad")
    op.drop_table("priv_plan_columnas")
    op.drop_table("priv_plan_prioridades")
    op.drop_table("priv_plan_estados")
    op.drop_table("priv_plan_programas")
