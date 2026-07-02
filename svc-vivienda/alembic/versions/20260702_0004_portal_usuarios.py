"""portal_usuarios — gestión de usuarios del portal

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_usuarios",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("nombre", sa.String(255)),
        sa.Column("rol", sa.String(50), nullable=False, server_default="Operador"),
        sa.Column("activo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(255)),
    )

    op.create_table(
        "portal_usuario_secretarias",
        sa.Column(
            "email",
            sa.String(255),
            sa.ForeignKey("portal_usuarios.email", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("secretaria", sa.String(100), primary_key=True),
    )

    # Seed: administradores iniciales con acceso a todas las secretarías
    op.execute("""
        INSERT INTO portal_usuarios (email, nombre, rol, activo, created_by) VALUES
        ('bonafepedro@gmail.com', 'Pedro Bonafe', 'Admin', true, 'system'),
        ('infraestructura.coop@gmail.com', 'Infraestructura Coop', 'Admin', true, 'system')
    """)

    op.execute("""
        INSERT INTO portal_usuario_secretarias (email, secretaria) VALUES
        ('bonafepedro@gmail.com', 'vivienda'),
        ('bonafepedro@gmail.com', 'privada'),
        ('infraestructura.coop@gmail.com', 'vivienda'),
        ('infraestructura.coop@gmail.com', 'privada')
    """)


def downgrade() -> None:
    op.drop_table("portal_usuario_secretarias")
    op.drop_table("portal_usuarios")
