"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # viv_programas
    op.create_table(
        "viv_programas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("codigo", sa.String(50), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("descripcion", sa.Text),
        sa.Column("activo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("requiere_ingreso_max", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("ingreso_max", sa.Numeric(14, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("codigo", name="uq_programa_codigo"),
    )

    # viv_beneficiarios
    op.create_table(
        "viv_beneficiarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dni", sa.String(20), nullable=False),
        sa.Column("cuil", sa.String(20)),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("apellido", sa.String(100), nullable=False),
        sa.Column("fecha_nacimiento", sa.String(10)),
        sa.Column("email", sa.String(200)),
        sa.Column("telefono", sa.String(30)),
        sa.Column("domicilio_calle", sa.String(200)),
        sa.Column("domicilio_numero", sa.String(20)),
        sa.Column("domicilio_localidad", sa.String(100)),
        sa.Column("domicilio_departamento", sa.String(100)),
        sa.Column("grupo_familiar_count", sa.Integer),
        sa.Column("ingreso_mensual", sa.Numeric(14, 2)),
        sa.Column("observaciones", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(200)),
        sa.Column("updated_by", sa.String(200)),
        sa.UniqueConstraint("dni", name="uq_beneficiario_dni"),
    )
    op.create_index("ix_beneficiarios_dni", "viv_beneficiarios", ["dni"])
    op.create_index("ix_beneficiarios_deleted_at", "viv_beneficiarios", ["deleted_at"])

    # viv_expedientes
    op.create_table(
        "viv_expedientes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("numero_expediente", sa.String(30), unique=True, nullable=False),
        sa.Column("beneficiario_id", sa.String(36), sa.ForeignKey("viv_beneficiarios.id"), nullable=False),
        sa.Column("programa_id", sa.String(36), sa.ForeignKey("viv_programas.id"), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("fecha_solicitud", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fecha_resolucion", sa.DateTime(timezone=True)),
        sa.Column("observaciones", sa.Text),
        sa.Column("prioridad", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(200)),
        sa.Column("updated_by", sa.String(200)),
    )
    op.create_index("ix_expedientes_estado", "viv_expedientes", ["estado"])
    op.create_index("ix_expedientes_beneficiario", "viv_expedientes", ["beneficiario_id"])
    op.create_index("ix_expedientes_programa", "viv_expedientes", ["programa_id"])
    op.create_index("ix_expedientes_deleted_at", "viv_expedientes", ["deleted_at"])

    # viv_historial_expedientes
    op.create_table(
        "viv_historial_expedientes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("expediente_id", sa.String(36), sa.ForeignKey("viv_expedientes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("estado_anterior", sa.String(30)),
        sa.Column("estado_nuevo", sa.String(30), nullable=False),
        sa.Column("observacion", sa.Text),
        sa.Column("actor_uid", sa.String(200), nullable=False),
        sa.Column("actor_rol", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_historial_expediente", "viv_historial_expedientes", ["expediente_id"])

    # viv_asignaciones
    op.create_table(
        "viv_asignaciones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("expediente_id", sa.String(36), sa.ForeignKey("viv_expedientes.id"), unique=True, nullable=False),
        sa.Column("tipo_bien", sa.String(20), nullable=False),
        sa.Column("identificador_bien", sa.String(100), nullable=False),
        sa.Column("domicilio_bien", sa.String(300)),
        sa.Column("fecha_escritura", sa.DateTime(timezone=True)),
        sa.Column("observaciones", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(200)),
        sa.UniqueConstraint("expediente_id", name="uq_asignacion_expediente"),
    )

    # viv_cordon_cuneta
    op.create_table(
        "viv_cordon_cuneta",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("municipio", sa.String(150), nullable=False),
        sa.Column("departamento", sa.String(100)),
        sa.Column("numero_expediente", sa.String(50)),
        sa.Column("monto", sa.Numeric(16, 2)),
        sa.Column("cordon_cuneta_ml", sa.Numeric(10, 2)),
        sa.Column("adoquinado_m2", sa.Numeric(10, 2)),
        sa.Column("est_documentacion", sa.String(100)),
        sa.Column("est_juridico_adm", sa.String(100)),
        sa.Column("est_tecnico", sa.String(100)),
        sa.Column("est_presup_fin", sa.String(100)),
        sa.Column("ok_ministerio", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("observaciones", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(200)),
    )

    # viv_audit_log
    op.create_table(
        "viv_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_uid", sa.String(200), nullable=False),
        sa.Column("actor_email", sa.String(200)),
        sa.Column("actor_role", sa.String(50)),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_resource", "viv_audit_log", ["resource_type", "resource_id"])
    op.create_index("ix_audit_log_actor", "viv_audit_log", ["actor_uid"])


def downgrade() -> None:
    op.drop_table("viv_audit_log")
    op.drop_table("viv_cordon_cuneta")
    op.drop_table("viv_asignaciones")
    op.drop_table("viv_historial_expedientes")
    op.drop_table("viv_expedientes")
    op.drop_table("viv_beneficiarios")
    op.drop_table("viv_programas")
