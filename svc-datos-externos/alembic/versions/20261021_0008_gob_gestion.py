"""Planillas de gestión territorial de Gobierno: obras, visitas, visitas del Gobernador,
reuniones y convenios

Espejos de solo lectura que se reemplazan completos en cada corrida (sin `deleted_at`, excepción
documentada, igual que la 0006 y la 0007). Ver
docs/files/spec-datos-externos-fase5-gestion-territorial.md §2.

Sin datos: los llena la primera corrida de
`POST /internal/datos-externos/gobierno/transferencias/sync`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer, primary_key=True, autoincrement=True)


def upgrade() -> None:
    op.create_table(
        "ext_gob_obra",
        _id(),
        sa.Column("id_obra", sa.String(40), nullable=False),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("codigo_zona_rural", sa.String(10)),
        sa.Column("ambito", sa.String(40)),
        sa.Column("localidad", sa.String(150)),
        sa.Column("departamento", sa.String(100)),
        sa.Column("nombre", sa.Text),
        sa.Column("division", sa.String(60)),
        sa.Column("estado", sa.String(60)),
        sa.Column("categoria", sa.String(60)),
        sa.Column("avance", sa.Float),
        sa.Column("fecha_inicio", sa.Date),
        sa.Column("fecha_fin", sa.Date),
        sa.Column("monto", sa.Numeric(18, 2)),
        *_ts(),
    )
    op.create_index("ix_ext_gob_obra_id_obra", "ext_gob_obra", ["id_obra"])
    op.create_index("ix_ext_gob_obra_codigo_indec", "ext_gob_obra", ["codigo_indec"])

    op.create_table(
        "ext_gob_visita",
        _id(),
        sa.Column("origen", sa.String(20), nullable=False),
        sa.Column("funcionario", sa.String(120)),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("localidad", sa.String(150)),
        sa.Column("departamento", sa.String(100)),
        sa.Column("tipo", sa.String(80)),
        *_ts(),
    )
    op.create_index("ix_ext_gob_visita_origen", "ext_gob_visita", ["origen"])
    op.create_index("ix_ext_gob_visita_codigo_indec", "ext_gob_visita", ["codigo_indec"])

    op.create_table(
        "ext_gob_visita_gobernador",
        sa.Column("codigo_indec", sa.String(20), primary_key=True),
        sa.Column("visitada", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("fecha_ultima", sa.Date),
        sa.Column("rango_habitantes", sa.String(40)),
        *_ts(),
    )

    op.create_table(
        "ext_gob_reunion",
        _id(),
        sa.Column("id_reu", sa.Integer),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("codigo_zona_rural", sa.String(10)),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("temas", sa.JSON, nullable=False),
        sa.Column("resolucion", sa.String(40)),
        *_ts(),
    )
    op.create_index("ix_ext_gob_reunion_codigo_indec", "ext_gob_reunion", ["codigo_indec"])

    op.create_table(
        "ext_gob_convenio",
        _id(),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("convenio", sa.String(60), nullable=False),
        sa.Column("valor", sa.String(10)),
        sa.Column("cantidad", sa.Integer),
        sa.Column("detalle", sa.String(40)),
        *_ts(),
    )
    op.create_index("ix_ext_gob_convenio_codigo_indec", "ext_gob_convenio", ["codigo_indec"])


def downgrade() -> None:
    for tabla in ("ext_gob_convenio", "ext_gob_reunion", "ext_gob_visita_gobernador", "ext_gob_visita", "ext_gob_obra"):
        op.drop_table(tabla)
