"""inicial: schema ag (capa semántica) + tablas del servicio

Revision ID: 0001
Revises:
Create Date: 2026-11-05

spec-agente-consultas.md §3 y §6.4, ADR-033.
Los roles de base (agente_app, agente_llm, agente_ro) NO se crean acá: tienen contraseña y
viven a nivel instancia — ver sql/roles_db_agente.sql y sql/grants_fuentes.sql. Esta migración
sólo da permisos a `agente_llm` si el rol ya existe.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_INDICES = [
    ("ag", "ag_programa_items", ["programa"]), ("ag", "ag_programa_items", ["id_geo"]),
    ("ag", "ag_programa_items", ["departamento"]), ("ag", "ag_gestiones", ["id_geo"]),
    ("ag", "ag_gestiones", ["departamento"]), ("ag", "ag_movimientos", ["programa", "origen_id"]),
    ("ag", "ag_hitos", ["programa", "origen_id"]), ("ag", "ag_transferencias", ["id_geo"]),
    ("ag", "ag_atp_pagos", ["id_geo"]), ("ag", "ag_localidades", ["departamento"]),
    ("ag", "ag_alias", ["texto_normalizado"]),
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ag")
    op.create_table('ag_alias',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('texto_normalizado', sa.String(length=200), nullable=False),
    sa.Column('departamento_normalizado', sa.String(length=120), nullable=False),
    sa.Column('id_geo', sa.String(length=30), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='ag'
    )
    op.create_table('ag_atp_pagos',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('fuente', sa.String(length=20), nullable=False),
    sa.Column('origen_id', sa.String(length=60), nullable=True),
    sa.Column('id_geo', sa.String(length=30), nullable=True),
    sa.Column('departamento', sa.String(length=120), nullable=True),
    sa.Column('localidad', sa.String(length=200), nullable=True),
    sa.Column('fecha', sa.Date(), nullable=True),
    sa.Column('monto', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='ag'
    )
    op.create_table('ag_frescura',
    sa.Column('fuente', sa.String(length=40), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('filas', sa.Integer(), nullable=False),
    sa.Column('ultimo_dato', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refrescado_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('mensaje', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('fuente'),
    schema='ag'
    )
    op.create_table('ag_gestiones',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('estado', sa.String(length=60), nullable=False),
    sa.Column('estado_normalizado', sa.String(length=30), nullable=False),
    sa.Column('urgencia', sa.String(length=30), nullable=True),
    sa.Column('area', sa.String(length=200), nullable=True),
    sa.Column('ministerio', sa.String(length=200), nullable=True),
    sa.Column('categoria', sa.String(length=200), nullable=True),
    sa.Column('categoria_general', sa.String(length=200), nullable=True),
    sa.Column('programa', sa.String(length=200), nullable=True),
    sa.Column('tipo_gestion', sa.String(length=120), nullable=True),
    sa.Column('canal_origen', sa.String(length=120), nullable=True),
    sa.Column('id_geo', sa.String(length=30), nullable=True),
    sa.Column('departamento', sa.String(length=120), nullable=True),
    sa.Column('localidad', sa.String(length=200), nullable=True),
    sa.Column('fecha_ingreso', sa.Date(), nullable=True),
    sa.Column('fecha_estado', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fecha_finalizacion', sa.Date(), nullable=True),
    sa.Column('dias_abierta', sa.Integer(), nullable=True),
    sa.Column('ok_gobernador', sa.String(length=20), nullable=True),
    sa.Column('ok_ministro', sa.String(length=20), nullable=True),
    sa.Column('costo_estimado', sa.Float(), nullable=True),
    sa.Column('detalle', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='ag'
    )
    op.create_table('ag_hitos',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('programa', sa.String(length=20), nullable=False),
    sa.Column('origen_id', sa.String(length=60), nullable=False),
    sa.Column('id_geo', sa.String(length=30), nullable=True),
    sa.Column('hito', sa.String(length=40), nullable=False),
    sa.Column('porcentaje', sa.Float(), nullable=False),
    sa.Column('monto', sa.Float(), nullable=True),
    sa.Column('fecha_acreditado', sa.Date(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='ag'
    )
    op.create_table('ag_localidades',
    sa.Column('id_geo', sa.String(length=30), nullable=False),
    sa.Column('localidad', sa.String(length=160), nullable=False),
    sa.Column('departamento', sa.String(length=120), nullable=False),
    sa.Column('poblacion', sa.Integer(), nullable=True),
    sa.Column('viviendas', sa.Integer(), nullable=True),
    sa.Column('intendente', sa.String(length=200), nullable=True),
    sa.Column('partido', sa.String(length=200), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('url_ficha', sa.String(length=400), nullable=True),
    sa.PrimaryKeyConstraint('id_geo'),
    schema='ag'
    )
    op.create_table('ag_movimientos',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('programa', sa.String(length=20), nullable=False),
    sa.Column('origen_id', sa.String(length=60), nullable=False),
    sa.Column('id_geo', sa.String(length=30), nullable=True),
    sa.Column('dimension', sa.String(length=30), nullable=False),
    sa.Column('estado_anterior', sa.String(length=300), nullable=True),
    sa.Column('estado_nuevo', sa.String(length=300), nullable=True),
    sa.Column('fecha', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='ag'
    )
    op.create_table('ag_programa_items',
    sa.Column('id', sa.String(length=120), nullable=False),
    sa.Column('programa', sa.String(length=20), nullable=False),
    sa.Column('programa_nombre', sa.String(length=80), nullable=False),
    sa.Column('secretaria', sa.String(length=40), nullable=False),
    sa.Column('origen_id', sa.String(length=60), nullable=False),
    sa.Column('nombre', sa.String(length=300), nullable=True),
    sa.Column('id_geo', sa.String(length=30), nullable=True),
    sa.Column('departamento', sa.String(length=120), nullable=True),
    sa.Column('localidad', sa.String(length=160), nullable=True),
    sa.Column('estado_origen', sa.String(length=300), nullable=True),
    sa.Column('estado_normalizado', sa.String(length=30), nullable=False),
    sa.Column('estado_tecnico', sa.String(length=120), nullable=True),
    sa.Column('avance', sa.Float(), nullable=True),
    sa.Column('cantidad', sa.Integer(), nullable=True),
    sa.Column('monto', sa.Float(), nullable=True),
    sa.Column('monto_ejecutado', sa.Float(), nullable=True),
    sa.Column('monto_usd', sa.Float(), nullable=True),
    sa.Column('fecha_inicio', sa.Date(), nullable=True),
    sa.Column('fecha_ultimo_cambio', sa.DateTime(timezone=True), nullable=True),
    sa.Column('url', sa.String(length=400), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    schema='ag'
    )
    op.create_table('ag_transferencias',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('id_geo', sa.String(length=30), nullable=True),
    sa.Column('departamento', sa.String(length=120), nullable=True),
    sa.Column('localidad', sa.String(length=200), nullable=True),
    sa.Column('tipo', sa.String(length=10), nullable=True),
    sa.Column('concepto', sa.String(length=50), nullable=False),
    sa.Column('periodo', sa.Date(), nullable=False),
    sa.Column('monto', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='ag'
    )
    op.create_table('ag_conversaciones',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ag_conversaciones_email'), 'ag_conversaciones', ['email'], unique=False)
    op.create_table('ag_interacciones',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('mensaje_id', sa.String(length=36), nullable=True),
    sa.Column('conversacion_id', sa.String(length=36), nullable=True),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('pregunta', sa.Text(), nullable=False),
    sa.Column('tools', sa.JSON(), nullable=True),
    sa.Column('sql', sa.JSON(), nullable=True),
    sa.Column('filas_devueltas', sa.Integer(), nullable=False),
    sa.Column('latencia_ms', sa.Integer(), nullable=False),
    sa.Column('tokens', sa.JSON(), nullable=True),
    sa.Column('costo_estimado_usd', sa.Float(), nullable=True),
    sa.Column('modelo', sa.String(length=60), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ag_interacciones_created_at'), 'ag_interacciones', ['created_at'], unique=False)
    op.create_index(op.f('ix_ag_interacciones_email'), 'ag_interacciones', ['email'], unique=False)
    op.create_index(op.f('ix_ag_interacciones_mensaje_id'), 'ag_interacciones', ['mensaje_id'], unique=False)
    op.create_table('ag_mensajes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversacion_id', sa.String(length=36), nullable=False),
    sa.Column('rol', sa.String(length=10), nullable=False),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('respuesta', sa.JSON(), nullable=True),
    sa.Column('api_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversacion_id'], ['ag_conversaciones.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ag_mensajes_conversacion_id'), 'ag_mensajes', ['conversacion_id'], unique=False)
    op.create_table('ag_feedback',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('mensaje_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('valor', sa.SmallInteger(), nullable=False),
    sa.Column('comentario', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['mensaje_id'], ['ag_mensajes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mensaje_id', 'email', name='uq_ag_feedback_mensaje_email')
    )

    for esquema, tabla, cols in _INDICES:
        op.create_index(f"ix_{tabla}_{'_'.join(cols)}", tabla, cols, schema=esquema)

    # Permisos del rol de consulta del modelo (spec §2.3): SELECT sólo sobre ag.*, nada en public.
    # En SQLite (tests) no aplica.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agente_llm') THEN
        GRANT USAGE ON SCHEMA ag TO agente_llm;
        GRANT SELECT ON ALL TABLES IN SCHEMA ag TO agente_llm;
        ALTER DEFAULT PRIVILEGES IN SCHEMA ag GRANT SELECT ON TABLES TO agente_llm;
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM agente_llm;
        -- search_path, read-only y statement_timeout del rol los fija sql/roles_db_agente.sql:
        -- ALTER ROLE exige CREATEROLE y agente_app (dueño de la base) no lo tiene.
      END IF;
    END $$;
    """)


def downgrade() -> None:
    for t in ("ag_feedback", "ag_interacciones", "ag_mensajes", "ag_conversaciones"):
        op.drop_table(t)
    for t in ("ag_localidades", "ag_alias", "ag_programa_items", "ag_gestiones", "ag_movimientos",
              "ag_hitos", "ag_transferencias", "ag_atp_pagos", "ag_frescura"):
        op.drop_table(t, schema="ag")
    op.execute("DROP SCHEMA IF EXISTS ag")
