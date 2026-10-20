"""Planillas de transferencias de Gobierno: COPA, FOFINDES, FODEMEP, FOMMEP y EMPLEADOS

Espejos de solo lectura que se reemplazan completos en cada corrida (sin `deleted_at`, excepción
documentada) y dos columnas de control de la Vista en `ext_gob_localidades`. Ver
docs/files/spec-datos-externos-fase2-transferencias.md §2.

Sin datos: los llena la primera corrida de
`POST /internal/datos-externos/gobierno/transferencias/sync`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_MONTO = sa.Numeric(18, 2)


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _m(nombre: str) -> sa.Column:
    return sa.Column(nombre, _MONTO)


def upgrade() -> None:
    op.create_table(
        "ext_gob_copa",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("mes", sa.Integer, nullable=False),
        sa.Column("quincena", sa.Integer, nullable=False),
        sa.Column("fecha_pago", sa.Date),
        sa.Column("id_copa", sa.Integer),
        sa.Column("indice", sa.Numeric(14, 10)),
        _m("bruto"), _m("ajuste"), _m("total_ajustado"), _m("neto_resultante"), _m("neto_a_transferir"),
        _m("caja_jubilaciones"), _m("apross"),
        sa.Column("descuentos", sa.JSON),
        *_ts(),
        sa.UniqueConstraint("codigo_indec", "anio", "mes", "quincena", name="uq_ext_gob_copa"),
    )
    op.create_index("ix_ext_gob_copa_codigo_indec", "ext_gob_copa", ["codigo_indec"])
    op.create_index("ix_ext_gob_copa_anio", "ext_gob_copa", ["anio"])

    op.create_table(
        "ext_gob_fofindes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("mes", sa.Integer, nullable=False),
        sa.Column("fecha_pago", sa.Date),
        _m("total_parte_variable"), _m("excedente_30"), _m("excedente_70"), _m("bruto"),
        sa.Column("descuentos", sa.JSON),
        _m("neto_resultante"), _m("neto_a_transferir"),
        *_ts(),
        sa.UniqueConstraint("codigo_indec", "anio", "mes", "fecha_pago", name="uq_ext_gob_fofindes"),
    )
    op.create_index("ix_ext_gob_fofindes_codigo_indec", "ext_gob_fofindes", ["codigo_indec"])
    op.create_index("ix_ext_gob_fofindes_anio", "ext_gob_fofindes", ["anio"])

    op.create_table(
        "ext_gob_fodemep",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("periodo", sa.Date, nullable=False),
        sa.Column("fecha_pago", sa.Date),
        _m("presupuestado"), _m("acumulado"), _m("neto_a_transferir"),
        *_ts(),
        sa.UniqueConstraint("codigo_indec", "periodo", name="uq_ext_gob_fodemep"),
    )
    op.create_index("ix_ext_gob_fodemep_codigo_indec", "ext_gob_fodemep", ["codigo_indec"])
    op.create_index("ix_ext_gob_fodemep_periodo", "ext_gob_fodemep", ["periodo"])

    op.create_table(
        "ext_gob_fodemep_estado",
        sa.Column("codigo_indec", sa.String(20), primary_key=True),
        sa.Column("estado", sa.String(30)),
        _m("saldo_gestion"),
        *_ts(),
    )

    op.create_table(
        "ext_gob_fommep",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("cant_moviles", sa.Integer), _m("monto_moviles"),
        sa.Column("cant_edificios_a", sa.Integer), _m("monto_edificios_a"),
        sa.Column("cant_edificios_b", sa.Integer), _m("monto_edificios_b"),
        sa.Column("cant_edificios_c", sa.Integer), _m("monto_edificios_c"),
        sa.Column("cant_edificios_total", sa.Integer), _m("monto_edificios_total"),
        _m("monto_total"),
        *_ts(),
        sa.UniqueConstraint("codigo_indec", "anio", name="uq_ext_gob_fommep"),
    )
    op.create_index("ix_ext_gob_fommep_codigo_indec", "ext_gob_fommep", ["codigo_indec"])

    op.create_table(
        "ext_gob_empleados",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codigo_indec", sa.String(20), nullable=False),
        sa.Column("anio", sa.Integer, nullable=False),
        # Restringidos: solo Admin y Autoridad (spec §6)
        sa.Column("empleados", sa.Integer),
        _m("salario_promedio"),
        _m("masa_salarial"),
        *_ts(),
        sa.UniqueConstraint("codigo_indec", "anio", name="uq_ext_gob_empleados"),
    )
    op.create_index("ix_ext_gob_empleados_codigo_indec", "ext_gob_empleados", ["codigo_indec"])

    # Control contra la Vista (spec §4.2): nunca se exponen.
    op.add_column("ext_gob_localidades", sa.Column("copa_vista_m", sa.Numeric(18, 4)))
    op.add_column("ext_gob_localidades", sa.Column("fofindes_vista_m", sa.Numeric(18, 4)))


def downgrade() -> None:
    op.drop_column("ext_gob_localidades", "fofindes_vista_m")
    op.drop_column("ext_gob_localidades", "copa_vista_m")
    for tabla in (
        "ext_gob_empleados", "ext_gob_fommep", "ext_gob_fodemep_estado", "ext_gob_fodemep",
        "ext_gob_fofindes", "ext_gob_copa",
    ):
        op.drop_table(tabla)
