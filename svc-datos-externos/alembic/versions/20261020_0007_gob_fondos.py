"""Planillas de fondos de Gobierno: Fondo Permanente, Fondo Ambiental y Comunidades Regionales

Espejos de solo lectura que se reemplazan completos en cada corrida (sin `deleted_at`, excepción
documentada, igual que la 0006). Ver docs/files/spec-datos-externos-fase3-fondos.md §2.

Sin datos: los llena la primera corrida de
`POST /internal/datos-externos/gobierno/transferencias/sync`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
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
        "ext_gob_fperm_localidad",
        sa.Column("codigo_indec", sa.String(20), primary_key=True),
        sa.Column("ultima_etapa", sa.Integer),
        sa.Column("disponible", _MONTO),
        sa.Column("recibio_ultima", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("recibio_anteultima", sa.Boolean, nullable=False, server_default=sa.false()),
        *_ts(),
    )

    op.create_table(
        "ext_gob_fperm_etapa",
        _id(),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("etapa", sa.Integer, nullable=False),
        sa.Column("monto", _MONTO),
        *_ts(),
        sa.UniqueConstraint("codigo_indec", "etapa", name="uq_ext_gob_fperm_etapa"),
    )
    op.create_index("ix_ext_gob_fperm_etapa_codigo_indec", "ext_gob_fperm_etapa", ["codigo_indec"])

    op.create_table(
        "ext_gob_fperm_prestamo",
        _id(),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("etapas_texto", sa.String(60)),
        sa.Column("etapa_desde", sa.Integer),
        sa.Column("etapa_hasta", sa.Integer),
        sa.Column("fecha", sa.Date),
        sa.Column("mes_inicio_descuento", sa.Integer),
        sa.Column("monto_total", _MONTO),
        sa.Column("cuota", _MONTO),
        sa.Column("plazo", sa.Integer),
        sa.Column("ord_res", sa.String(60)),
        sa.Column("sticker", sa.String(120)),
        sa.Column("fecha_ingreso", sa.Date),
        sa.Column("destino", sa.Text),
        *_ts(),
    )
    op.create_index("ix_ext_gob_fperm_prestamo_codigo_indec", "ext_gob_fperm_prestamo", ["codigo_indec"])

    op.create_table(
        "ext_gob_fondo_ambiental",
        _id(),
        sa.Column("codigo_indec", sa.String(20)),
        sa.Column("codigo_ente", sa.String(20)),
        sa.Column("nombre_ente", sa.String(150)),
        sa.Column("departamento_ente", sa.String(100)),
        sa.Column("anio", sa.Integer),
        sa.Column("expediente", sa.String(60)),
        sa.Column("convenio", sa.String(60)),
        sa.Column("fecha_convenio", sa.Date),
        sa.Column("resolucion", sa.String(60)),
        sa.Column("fecha_resolucion", sa.Date),
        sa.Column("objeto", sa.Text),
        sa.Column("monto", _MONTO),
        sa.Column("estado", sa.String(40)),
        sa.Column("fecha_estado", sa.Date),
        *_ts(),
    )
    op.create_index("ix_ext_gob_fondo_ambiental_codigo_indec", "ext_gob_fondo_ambiental", ["codigo_indec"])
    op.create_index("ix_ext_gob_fondo_ambiental_anio", "ext_gob_fondo_ambiental", ["anio"])

    op.create_table(
        "ext_gob_creg_cuota",
        _id(),
        sa.Column("codigo_ente", sa.String(20)),
        sa.Column("tipo", sa.String(30)),
        sa.Column("anio", sa.Integer),
        sa.Column("expediente", sa.String(60)),
        sa.Column("destino", sa.Text),
        sa.Column("monto", _MONTO),
        sa.Column("cuota", sa.Integer),
        sa.Column("monto_cuota", _MONTO),
        sa.Column("estado", sa.String(40)),
        sa.Column("fecha_pago", sa.Date),
        sa.Column("resolucion", sa.String(60)),
        sa.Column("fecha_rendicion", sa.Date),
        *_ts(),
    )
    op.create_index("ix_ext_gob_creg_cuota_codigo_ente", "ext_gob_creg_cuota", ["codigo_ente"])
    op.create_index("ix_ext_gob_creg_cuota_anio", "ext_gob_creg_cuota", ["anio"])

    op.create_table(
        "ext_gob_fondo_valor",
        _id(),
        sa.Column("fondo", sa.String(40), nullable=False),
        sa.Column("concepto", sa.String(40), nullable=False),
        sa.Column("anio", sa.Integer),
        sa.Column("monto", _MONTO),
        *_ts(),
        sa.UniqueConstraint("fondo", "concepto", "anio", name="uq_ext_gob_fondo_valor"),
    )


def downgrade() -> None:
    for tabla in (
        "ext_gob_fondo_valor",
        "ext_gob_creg_cuota",
        "ext_gob_fondo_ambiental",
        "ext_gob_fperm_prestamo",
        "ext_gob_fperm_etapa",
        "ext_gob_fperm_localidad",
    ):
        op.drop_table(tabla)
