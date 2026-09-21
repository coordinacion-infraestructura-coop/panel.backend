"""gas_pit sync — espejo de solo lectura del Sheet "SEC. GAS PIT"

Fase 0 de svc-gasifera (ver docs/files/spec-sync-gasifera-pit.md): solo las
tablas del sync, sin módulo de negocio. Alcance: obras de gas (subconjunto de
MATRIZ (NO TOMAR)) + acciones territoriales (ACCIONES TERRITORIO, ya 100% gas).

Revision ID: 0001
Revises:
Create Date: 2026-09-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gas_pit_obras",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("spip", sa.String(30)),
        sa.Column("expediente", sa.String(60)),
        sa.Column("division", sa.String(50)),
        sa.Column("nombre_obra", sa.String(300), nullable=False),
        sa.Column("nombre_obra_norm", sa.String(300), nullable=False),
        sa.Column("departamento_norm", sa.String(100), nullable=False, server_default=""),
        sa.Column("tipo_obra", sa.String(100)),
        sa.Column("sub_tipo_obra", sa.String(50), nullable=False, server_default="E- OBRAS DE GAS"),
        sa.Column("contratista", sa.String(200)),
        sa.Column("estado_obra", sa.String(60)),
        sa.Column("estado_resumen", sa.String(30)),
        sa.Column("departamento", sa.String(100)),
        sa.Column("avance", sa.Numeric(5, 4)),
        sa.Column("repla_inicial", sa.Date),
        sa.Column("fecha_lic", sa.Date),
        sa.Column("vencimiento", sa.Date),
        sa.Column("plazo_vigente_dias", sa.Integer),
        sa.Column("plazo_original", sa.Integer),
        sa.Column("contrato_base", sa.Numeric(18, 2)),
        sa.Column("ampliacion", sa.Numeric(18, 2)),
        sa.Column("enmienda", sa.Numeric(18, 2)),
        sa.Column("importe_obra_actualizado", sa.Numeric(18, 2)),
        sa.Column("importe_dolar", sa.Numeric(18, 2)),
        sa.Column("prioridad", sa.String(60)),
        sa.Column("categoria", sa.SmallInteger),
        sa.Column("region", sa.String(30)),
        sa.Column("autorizada_2025", sa.String(60)),
        sa.Column("pit", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("sheet_row_number", sa.Integer, nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("nombre_obra_norm", "departamento_norm", name="uq_gas_pit_obra_nombre_depto"),
    )

    op.create_table(
        "gas_pit_obras_localidades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "obra_id", sa.String(36),
            sa.ForeignKey("gas_pit_obras.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("localidad", sa.String(150), nullable=False),
        sa.UniqueConstraint("obra_id", "localidad", name="uq_gas_pit_obra_localidad"),
    )

    op.create_table(
        "gas_pit_acciones_territorio",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fecha", sa.Date),
        sa.Column("departamento", sa.String(100)),
        sa.Column("localidad", sa.String(150)),
        sa.Column("id_accion", sa.String(50)),
        sa.Column("accion", sa.String(200)),
        sa.Column("detalle_accion", sa.Text),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("monto_inversion_solicitado", sa.Numeric(18, 2)),
        sa.Column("comentarios", sa.Text),
        sa.Column("monto_inversion_usd", sa.Numeric(18, 2)),
        sa.Column("alerta_localidad", sa.String(200)),
        sa.Column("sheet_row_number", sa.Integer, nullable=False, unique=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "gas_pit_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("filas_leidas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_insertadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_actualizadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_error", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errores", sa.Text),
        sa.Column("triggered_by", sa.String(50)),
    )


def downgrade() -> None:
    op.drop_table("gas_pit_sync_log")
    op.drop_table("gas_pit_acciones_territorio")
    op.drop_table("gas_pit_obras_localidades")
    op.drop_table("gas_pit_obras")
