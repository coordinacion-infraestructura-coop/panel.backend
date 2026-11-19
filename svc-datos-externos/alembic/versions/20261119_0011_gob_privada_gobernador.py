"""Planilla "Gobierno" de la Privada del Gobernador: anuncios, FOCOM y ATP histórico

Espejos de solo lectura que se reemplazan completos en cada corrida (sin `deleted_at`, misma
excepción documentada que la 0006 y la 0007). Ver
docs/files/spec-datos-externos-privada-gobernador.md §2.

Sin datos: los llena la primera corrida de
`POST /internal/datos-externos/gobierno/transferencias/sync` (fuentes `anuncios_gobernador`,
`focom` y `atp_historico`).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_MONTO = sa.Numeric(18, 2)


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer, primary_key=True, autoincrement=True)


def upgrade() -> None:
    op.create_table(
        "ext_gob_anuncio",
        _id(),
        sa.Column("ascasu", sa.Integer, nullable=False),
        sa.Column("fecha_carga", sa.Date),
        sa.Column("fecha_anuncio", sa.Date),
        sa.Column("fecha_anuncio_texto", sa.String(30)),
        sa.Column("fuente_url", sa.Text),
        sa.Column("departamento", sa.String(100)),
        sa.Column("localidad", sa.String(150)),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("ministerio", sa.String(100)),
        sa.Column("anuncio", sa.Text),
        sa.Column("detalle", sa.Text),
        sa.Column("estado", sa.String(40)),
        sa.Column("linea_base", sa.Numeric(18, 4)),
        sa.Column("valor_actual", sa.Numeric(18, 4)),
        sa.Column("grado_cumplimiento", sa.Numeric(8, 4)),
        sa.Column("comentarios", sa.Text),
        sa.Column("indicador_seguimiento", sa.String(40)),
        sa.Column("estado_seguimiento", sa.String(40)),
        sa.Column("coinciden", sa.Boolean),
        sa.Column("montos_mencionados", sa.JSON),
        sa.Column("hash_contenido", sa.String(64), nullable=False),
        *_ts(),
        sa.UniqueConstraint("ascasu", name="uq_ext_gob_anuncio_ascasu"),
    )
    op.create_index("ix_ext_gob_anuncio_fecha_anuncio", "ext_gob_anuncio", ["fecha_anuncio"])
    op.create_index("ix_ext_gob_anuncio_codigo_indec", "ext_gob_anuncio", ["codigo_indec"])

    op.create_table(
        "ext_gob_focom",
        _id(),
        sa.Column("id_focom", sa.String(30), nullable=False),
        sa.Column("ocurrencia", sa.Integer, nullable=False, server_default="1"),
        sa.Column("expediente", sa.String(60)),
        sa.Column("convenio", sa.String(60)),
        sa.Column("fecha_convenio", sa.Date),
        sa.Column("resolucion", sa.String(60)),
        sa.Column("departamento", sa.String(100)),
        sa.Column("tipo", sa.String(40)),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("localidad", sa.String(150)),
        sa.Column("monto", _MONTO),
        sa.Column("concepto", sa.Text),
        sa.Column("categoria", sa.String(60)),
        sa.Column("estado", sa.String(40)),
        sa.Column("fecha_pago", sa.Date),
        sa.Column("plazo_visacion", sa.String(60)),
        sa.Column("anio", sa.Integer),
        sa.Column("estado_obra", sa.String(40)),
        *_ts(),
        sa.UniqueConstraint("id_focom", "ocurrencia", name="uq_ext_gob_focom"),
    )
    op.create_index("ix_ext_gob_focom_id_focom", "ext_gob_focom", ["id_focom"])
    op.create_index("ix_ext_gob_focom_codigo_indec", "ext_gob_focom", ["codigo_indec"])
    op.create_index("ix_ext_gob_focom_anio", "ext_gob_focom", ["anio"])

    op.create_table(
        "ext_gob_atp_historico",
        _id(),
        sa.Column("id_atp", sa.String(30), nullable=False),
        sa.Column("ocurrencia", sa.Integer, nullable=False, server_default="1"),
        sa.Column("departamento", sa.String(100)),
        sa.Column("localidad", sa.String(150)),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("monto", _MONTO, nullable=False),
        *_ts(),
        sa.UniqueConstraint("id_atp", "ocurrencia", name="uq_ext_gob_atp_historico"),
    )
    op.create_index("ix_ext_gob_atp_historico_id_atp", "ext_gob_atp_historico", ["id_atp"])
    op.create_index("ix_ext_gob_atp_historico_codigo_indec", "ext_gob_atp_historico", ["codigo_indec"])
    op.create_index("ix_ext_gob_atp_historico_anio", "ext_gob_atp_historico", ["anio"])


def downgrade() -> None:
    op.drop_table("ext_gob_atp_historico")
    op.drop_table("ext_gob_focom")
    op.drop_table("ext_gob_anuncio")
