"""Padrón de intendentes y resultados electorales de Gobierno

Espejos de solo lectura que se reemplazan completos en cada corrida (sin `deleted_at`, excepción
documentada, igual que la 0006 a la 0008). Ver docs/files/spec-datos-externos-fase6-politico.md §2.

Sin datos: los llena la primera corrida de
`POST /internal/datos-externos/gobierno/transferencias/sync`.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
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
        "ext_gob_intendente",
        sa.Column("codigo_indec", sa.String(20), primary_key=True),
        sa.Column("intendente", sa.String(150)),
        sa.Column("reelecto", sa.Boolean),
        sa.Column("partido", sa.String(150)),
        sa.Column("continuidad", sa.Boolean),
        sa.Column("celular", sa.String(30)),
        sa.Column("foto_url", sa.String(500)),
        *_ts(),
    )

    op.create_table(
        "ext_gob_eleccion_circuito",
        _id(),
        sa.Column("eleccion", sa.String(30), nullable=False),
        sa.Column("circuito_id", sa.String(20), nullable=False),
        sa.Column("circuito_nombre", sa.String(150)),
        sa.Column("departamento", sa.String(100)),
        sa.Column("padron", sa.Integer),
        sa.Column("mesas", sa.Integer),
        sa.Column("nulos", sa.Integer),
        sa.Column("blancos", sa.Integer),
        sa.Column("impugnados", sa.Integer),
        sa.Column("recurridos", sa.Integer),
        sa.Column("total_votos", sa.Integer),
        sa.Column("afirmativos", sa.Integer),
        sa.Column("validos", sa.Integer),
        sa.Column("votos", sa.JSON, nullable=False),
        *_ts(),
    )
    op.create_index("ix_ext_gob_eleccion_circuito_eleccion", "ext_gob_eleccion_circuito", ["eleccion"])

    op.create_table(
        "ext_gob_circuito_localidad",
        sa.Column("circuito_id", sa.String(20), primary_key=True),
        sa.Column("localidad", sa.String(150), nullable=False),
        sa.Column("codigo_indec", sa.String(20)),
        *_ts(),
    )
    op.create_index("ix_ext_gob_circuito_localidad_codigo_indec", "ext_gob_circuito_localidad", ["codigo_indec"])

    op.create_table(
        "ext_gob_eleccion_municipal",
        sa.Column("codigo_indec", sa.String(20), primary_key=True),
        sa.Column("periodo", sa.String(20)),
        sa.Column("tipo_gobierno", sa.String(40)),
        sa.Column("fecha", sa.Date),
        sa.Column("participacion", sa.Float),
        sa.Column("afirmativos", sa.Integer),
        sa.Column("padron", sa.Integer),
        sa.Column("ganador_partido", sa.String(200)),
        sa.Column("ganador_partido_norm", sa.String(100)),
        sa.Column("ganador_votos", sa.Integer),
        sa.Column("ganador_pct", sa.Float),
        sa.Column("ganador_nombre", sa.String(150)),
        sa.Column("ganador_sexo", sa.String(10)),
        sa.Column("segundo_partido", sa.String(200)),
        sa.Column("segundo_partido_norm", sa.String(100)),
        sa.Column("segundo_votos", sa.Integer),
        sa.Column("segundo_pct", sa.Float),
        sa.Column("segundo_nombre", sa.String(150)),
        sa.Column("otras_votos", sa.Integer),
        sa.Column("otras_pct", sa.Float),
        *_ts(),
    )

    op.create_table(
        "ext_gob_eleccion_copia",
        _id(),
        sa.Column("pestana", sa.String(40), nullable=False),
        sa.Column("localidad", sa.String(150), nullable=False),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("datos", sa.JSON, nullable=False),
        *_ts(),
    )
    op.create_index("ix_ext_gob_eleccion_copia_pestana", "ext_gob_eleccion_copia", ["pestana"])
    op.create_index("ix_ext_gob_eleccion_copia_codigo_indec", "ext_gob_eleccion_copia", ["codigo_indec"])


def downgrade() -> None:
    op.drop_table("ext_gob_eleccion_copia")
    op.drop_table("ext_gob_eleccion_municipal")
    op.drop_table("ext_gob_circuito_localidad")
    op.drop_table("ext_gob_eleccion_circuito")
    op.drop_table("ext_gob_intendente")
