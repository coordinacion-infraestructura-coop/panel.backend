"""Planilla "0. Fondo Federal" de Gobierno: etapas habilitadas y aportes/devoluciones COPA

Espejos de solo lectura que se reemplazan completos en cada corrida (sin `deleted_at`, misma
excepción documentada que la 0006 y la 0007). Ver
docs/files/spec-datos-externos-fase3b-fondo-federal.md §2. Los valores del `0. Resumen` van a
`ext_gob_fondo_valor` (fondo `fondo_federal`), que ya existe.

Cuelga de la 0011: la 0012 (acciones en territorio) está en otra rama sin mergear. La que se
mergee segunda tiene que encadenarse a la otra (`down_revision`).

Sin datos: los llena la primera corrida de
`POST /internal/datos-externos/gobierno/transferencias/sync` (fuente `fondo_federal`).

Revision ID: 0013
Revises: 0011
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0011"
branch_labels = None
depends_on = None

_MONTO = sa.Numeric(18, 2)


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "ext_gob_ffed_etapa",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("fila", sa.Integer, nullable=False),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("etapa_texto", sa.String(60), nullable=False),
        sa.Column("etapa_numero", sa.Integer),
        sa.Column("es_extra", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("resolucion", sa.String(30)),
        sa.Column("fecha_resolucion", sa.Date),
        sa.Column("tipo", sa.String(5)),
        sa.Column("categoria", sa.Integer),
        sa.Column("monto_etapa", _MONTO),
        sa.Column("disponible_etapa", _MONTO),
        sa.Column("estado", sa.String(40)),
        sa.Column("ord_res", sa.String(60)),
        sa.Column("fecha_ingreso", sa.Date),
        sa.Column("sticker_pedido", sa.String(40)),
        sa.Column("otorgado", _MONTO),
        sa.Column("cuota", _MONTO),
        sa.Column("plazo", sa.Integer),
        sa.Column("fecha_entrega", sa.Date),
        sa.Column("inicio_descuento", sa.Date),
        sa.Column("sticker_rendicion", sa.String(40)),
        sa.Column("destino", sa.String(120)),
        sa.Column("destino_detalle", sa.Text),
        sa.Column("saldo", _MONTO),
        sa.Column("devuelto", _MONTO),
        sa.Column("cuotas_devueltas", sa.Integer),
        sa.Column("amortizada", sa.Boolean),
        sa.Column("observaciones", sa.Text),
        sa.Column("fecha_aviso", sa.Date),
        sa.Column("aviso_texto", sa.Text),
        sa.Column("tramite", sa.String(40)),
        *_ts(),
    )
    op.create_index("ix_ext_gob_ffed_etapa_codigo_indec", "ext_gob_ffed_etapa", ["codigo_indec"])
    op.create_index("ix_ext_gob_ffed_etapa_estado", "ext_gob_ffed_etapa", ["estado"])

    op.create_table(
        "ext_gob_ffed_copa",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("aporte", _MONTO),
        sa.Column("devolucion", _MONTO),
        *_ts(),
        sa.UniqueConstraint("codigo_indec", "anio", name="uq_ext_gob_ffed_copa"),
    )
    op.create_index("ix_ext_gob_ffed_copa_codigo_indec", "ext_gob_ffed_copa", ["codigo_indec"])


def downgrade() -> None:
    op.drop_table("ext_gob_ffed_copa")
    op.drop_table("ext_gob_ffed_etapa")
