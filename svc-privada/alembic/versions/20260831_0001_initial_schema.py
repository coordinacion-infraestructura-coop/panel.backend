"""initial schema — svc-privada (migración desde BigQuery infra_gestion)

Crea el schema priv_* de paridad (spec-migracion-svc-privada.md §4). NO incluye las
tablas de mejora (priv_categorias / priv_programas / priv_areas / priv_gestion_derivaciones)
— esas las agregan migraciones posteriores de los specs hijos.

Revision ID: 0001
Revises:
Create Date: 2026-08-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_ESTADOS = (
    "INGRESADO",
    "DERIVADO A SUAC",
    "LISTA PARA INNAUGURAR",
    "FINALIZADA",
    "NO REMITE SUAC",
    "ARCHIVADO",
)
_URGENCIAS = ("Alta", "Media", "Baja")
_ESTADOS_SQL = ", ".join(f"'{e}'" for e in _ESTADOS)
_URGENCIAS_SQL = ", ".join(f"'{u}'" for u in _URGENCIAS)


def _catalogo(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("orden", sa.Integer),
        sa.Column("activo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("descripcion", sa.Text),
    )


def upgrade() -> None:
    # ── Catálogos legacy (migrados 1:1 desde infra_gestion.cat_*) ─────────────
    for cat in (
        "priv_cat_estado",
        "priv_cat_urgencia",
        "priv_cat_ministerio_agencia",
        "priv_cat_categoria_general",
        "priv_cat_tipo_gestion",
        "priv_cat_canal_origen",
    ):
        _catalogo(cat)

    # ── Referencia geoespacial ──────────────────────────────────────────────
    op.create_table(
        "priv_geo_localidades",
        sa.Column("id_geo", sa.String(30), primary_key=True),
        sa.Column("departamento", sa.String(120), nullable=False),
        sa.Column("localidad", sa.String(200), nullable=False),
        sa.Column("lat", sa.Numeric(12, 7)),  # ex lat_centro
        sa.Column("lon", sa.Numeric(12, 7)),  # ex lon_centro
        sa.Column("activo", sa.Boolean, nullable=False, server_default="true"),
    )

    # ── Datos enriquecidos por localidad / departamento (ADR-012) ───────────
    op.create_table(
        "priv_localidades_info",
        sa.Column("departamento", sa.String(120), primary_key=True),
        sa.Column("localidad", sa.String(160), primary_key=True),
        sa.Column("habitantes", sa.Integer),
        sa.Column("electores", sa.Integer),
        sa.Column("intendente_jefe_comunal", sa.String(200)),
        sa.Column("partido_politico", sa.String(200)),
        sa.Column("tipo_localidad", sa.String(60)),
        sa.Column("color_semaforo", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.String(200)),
    )
    op.create_table(
        "priv_departamentos_info",
        sa.Column("departamento", sa.String(120), primary_key=True),
        sa.Column("habitantes", sa.Integer),
        sa.Column("electores", sa.Integer),
        sa.Column("legislador_departamental", sa.String(200)),
        sa.Column("partido_politico", sa.String(200)),
        sa.Column("legislador_sabana1", sa.String(200)),
        sa.Column("partido_politico_sabana1", sa.String(200)),
        sa.Column("legislador_sabana2", sa.String(200)),
        sa.Column("partido_politico_sabana2", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.String(200)),
    )

    # ── Gestiones ──────────────────────────────────────────────────────────
    op.create_table(
        "priv_gestiones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("id_legacy", sa.String(100)),
        sa.Column("nro_expediente", sa.String(120)),
        sa.Column("origen", sa.String(100)),
        sa.Column("estado", sa.String(60), nullable=False, server_default="INGRESADO"),
        sa.Column("fecha_ingreso", sa.Date, nullable=False),
        sa.Column("fecha_estado", sa.DateTime(timezone=True)),
        sa.Column("fecha_finalizacion", sa.Date),
        sa.Column("urgencia", sa.String(30), server_default="Media"),
        sa.Column("ministerio_agencia_id", sa.String(120)),
        sa.Column("organismo_id", sa.String(300)),
        sa.Column("derivado_a_id", sa.String(300)),
        sa.Column("categoria_general_id", sa.String(120)),
        sa.Column("subcategoria_id", sa.String(120)),
        sa.Column("tipo_demanda_principal_id", sa.String(120)),
        sa.Column("subtipo_detalle", sa.Text),
        sa.Column("detalle", sa.Text, nullable=False),
        sa.Column("observaciones", sa.Text),
        sa.Column("geo_id", sa.String(60)),
        sa.Column("departamento", sa.String(120), nullable=False),
        sa.Column("localidad", sa.String(200), nullable=False),
        sa.Column("direccion", sa.Text),
        sa.Column("lat", sa.Numeric(12, 7)),
        sa.Column("lon", sa.Numeric(12, 7)),
        sa.Column("costo_estimado", sa.Numeric(18, 2)),
        sa.Column("costo_moneda", sa.String(20)),
        sa.Column("tipo_gestion", sa.String(120)),
        sa.Column("canal_origen", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(200)),
        sa.Column("updated_by", sa.String(200)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["ministerio_agencia_id"],
            ["priv_cat_ministerio_agencia.id"],
            name="fk_priv_gestion_ministerio",
        ),
        sa.ForeignKeyConstraint(
            ["categoria_general_id"],
            ["priv_cat_categoria_general.id"],
            name="fk_priv_gestion_categoria",
        ),
        sa.UniqueConstraint("id_legacy", name="uq_priv_gestiones_id_legacy"),
        sa.CheckConstraint(f"estado IN ({_ESTADOS_SQL})", name="ck_priv_gestiones_estado"),
        sa.CheckConstraint(f"urgencia IN ({_URGENCIAS_SQL})", name="ck_priv_gestiones_urgencia"),
    )
    op.create_index("ix_priv_gestiones_depto_loc", "priv_gestiones", ["departamento", "localidad"])
    op.create_index("ix_priv_gestiones_estado", "priv_gestiones", ["estado"])
    op.create_index("ix_priv_gestiones_fecha_ingreso", "priv_gestiones", ["fecha_ingreso"])
    op.create_index("ix_priv_gestiones_nro_expediente", "priv_gestiones", ["nro_expediente"])
    op.create_index("ix_priv_gestiones_deleted_at", "priv_gestiones", ["deleted_at"])

    # ── Eventos de gestión (log append-only) ───────────────────────────────
    op.create_table(
        "priv_gestiones_eventos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gestion_id", sa.String(36), nullable=False),
        sa.Column("fecha_evento", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usuario", sa.String(200), nullable=False),
        sa.Column("rol_usuario", sa.String(40)),
        sa.Column("tipo_evento", sa.String(60), nullable=False),
        sa.Column("estado_anterior", sa.String(60)),
        sa.Column("estado_nuevo", sa.String(60)),
        sa.Column("campo_modificado", sa.String(100)),
        sa.Column("valor_anterior", sa.Text),
        sa.Column("valor_nuevo", sa.Text),
        sa.Column("comentario", sa.Text),
        sa.Column("metadata_json", sa.JSON),
        sa.ForeignKeyConstraint(
            ["gestion_id"], ["priv_gestiones.id"], name="fk_priv_evento_gestion"
        ),
    )
    op.create_index(
        "ix_priv_eventos_gestion_fecha",
        "priv_gestiones_eventos",
        ["gestion_id", "fecha_evento"],
    )

    # ── Audit log (write-only, sin endpoint de lectura) ────────────────────
    op.create_table(
        "priv_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_uid", sa.String(200), nullable=False),
        sa.Column("actor_email", sa.String(200)),
        sa.Column("actor_role", sa.String(40)),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("resource_type", sa.String(60), nullable=False),
        sa.Column("resource_id", sa.String(200)),
        sa.Column("payload", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_priv_audit_resource", "priv_audit_log", ["resource_type", "resource_id"]
    )
    op.create_index("ix_priv_audit_actor", "priv_audit_log", ["actor_uid"])


def downgrade() -> None:
    op.drop_table("priv_audit_log")
    op.drop_table("priv_gestiones_eventos")
    op.drop_table("priv_gestiones")
    op.drop_table("priv_departamentos_info")
    op.drop_table("priv_localidades_info")
    op.drop_table("priv_geo_localidades")
    for cat in (
        "priv_cat_canal_origen",
        "priv_cat_tipo_gestion",
        "priv_cat_categoria_general",
        "priv_cat_ministerio_agencia",
        "priv_cat_urgencia",
        "priv_cat_estado",
    ):
        op.drop_table(cat)
