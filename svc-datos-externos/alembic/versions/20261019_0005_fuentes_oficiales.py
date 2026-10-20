"""Fuentes oficiales públicas por gobierno local

Estadística Córdoba (Censo 2010/2022 por gobierno local, condiciones de vida,
educación, salud, empleo, IPS), RENABAP y equipamientos y estadísticas
vitales de IDECOR. Ver docs/files/spec-datos-externos-fuentes-oficiales.md §3.

Sin datos: los llena la primera corrida de
`POST /internal/datos-externos/fuentes-oficiales/sync`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def _f(nombre: str) -> sa.Column:
    return sa.Column(nombre, sa.Float)


def _i(nombre: str) -> sa.Column:
    return sa.Column(nombre, sa.Integer)


def upgrade() -> None:
    op.create_table(
        "ext_est_gobierno_local",
        sa.Column("codigo_indec", sa.String(10), primary_key=True),
        sa.Column("nombre", sa.String(150)),
        sa.Column("codigo_dpto_indec", sa.String(10)),
        sa.Column("tipo_2022", sa.String(10)),
        _i("poblacion_2010"), _i("poblacion_2022"), _f("variacion_intercensal"),
        sa.Column("superficie_km2", sa.Numeric(12, 4)),
        _f("densidad"), _i("hogares"), _f("personas_por_hogar"), _f("pct_0_17"), _f("pct_65_mas"), _f("coef_vejez"),
        _f("nbi_pct"), _f("nbi_vivienda_pct"), _f("nbi_sanitaria_pct"), _f("nbi_hacinamiento_pct"),
        _f("nbi_escolar_pct"), _f("nbi_subsistencia_pct"),
        _f("agua_red_pct"), _f("cloacas_pct"), _f("gas_red_pct"), _f("internet_pct"),
        _f("propietarios_pct"), _f("inquilinos_pct"), _f("otra_tenencia_pct"),
        _f("calidad_i_pct"), _f("calidad_ii_pct"), _f("calidad_iii_pct"), _f("calidad_iv_pct"),
        _i("hogares_total"), _i("hogares_hacinamiento"), _i("hogares_sanitaria"),
        _i("hogares_vivienda_inconveniente"), _i("hogares_calidad_iii"), _i("hogares_calidad_iv"),
        _i("hogares_lena_carbon"), _i("hogares_alquilan"),
        _f("asistencia_10_18_pct"), _f("secundario_completo_pct"), _f("universitario_completo_pct"),
        _f("cobertura_salud_pct"), _f("desocupacion_pct"),
        sa.Column("actividad_principal", sa.String(200)),
        _f("ips_valor"), sa.Column("ips_nivel", sa.String(30)), _f("ips_necesidades_basicas"),
        _f("ips_fundamentos_bienestar"), _f("ips_oportunidades"), _f("ips_variacion_interanual"),
        sa.Column("crudo", sa.JSON),
        sa.Column("synced_at", _TS, nullable=False),
    )
    op.create_table(
        "ext_est_departamento",
        sa.Column("codigo_dpto_indec", sa.String(10), primary_key=True),
        sa.Column("nombre", sa.String(100)),
        _i("poblacion_2010"), _i("poblacion_2022"),
        sa.Column("superficie_km2", sa.Numeric(12, 2)),
        _i("poblacion_fuera_gl_2010"), _i("poblacion_fuera_gl_2022"),
        sa.Column("synced_at", _TS, nullable=False),
    )
    op.create_table(
        "ext_est_poligonos",
        sa.Column("codigo_indec", sa.String(10), primary_key=True),
        sa.Column("geojson", sa.JSON, nullable=False),
        sa.Column("synced_at", _TS, nullable=False),
    )
    op.create_table(
        "ext_renabap_barrios",
        sa.Column("id_renabap", sa.String(20), primary_key=True),
        sa.Column("nombre", sa.String(200)),
        _i("familias"), _i("anio_creacion"),
        sa.Column("decada_creacion", sa.String(40)),
        sa.Column("tipologia", sa.String(80)),
        sa.Column("situacion_dominial", sa.String(80)),
        sa.Column("energia", sa.String(150)),
        sa.Column("cloacas", sa.String(150)),
        sa.Column("agua", sa.String(150)),
        sa.Column("gas", sa.String(150)),
        _f("superficie_km2"), _f("lat"), _f("lng"),
        sa.Column("codigo_radio", sa.String(20)),
        sa.Column("codigo_indec", sa.String(10)),
        sa.Column("version", sa.String(10)),
        sa.Column("synced_at", _TS, nullable=False),
    )
    op.create_index("ix_ext_renabap_barrios_codigo_indec", "ext_renabap_barrios", ["codigo_indec"])
    op.create_table(
        "ext_equipamientos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("codigo_fuente", sa.String(40)),
        sa.Column("nombre", sa.String(250)),
        sa.Column("categoria", sa.String(250)),
        sa.Column("sector", sa.String(80)),
        sa.Column("ambito", sa.String(80)),
        sa.Column("localidad_fuente", sa.String(150)),
        sa.Column("departamento_fuente", sa.String(100)),
        _f("lat"), _f("lng"),
        sa.Column("codigo_indec", sa.String(10)),
        sa.Column("synced_at", _TS, nullable=False),
    )
    op.create_index("ix_ext_equipamientos_tipo_codigo", "ext_equipamientos", ["tipo", "codigo_indec"])
    op.create_table(
        "ext_estadisticas_vitales",
        sa.Column("radio_idecor", sa.String(150), primary_key=True),
        sa.Column("anio", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String(20), primary_key=True),
        _i("total"),
        sa.Column("codigo_indec", sa.String(10)),
        sa.Column("synced_at", _TS, nullable=False),
    )
    op.create_index("ix_ext_estadisticas_vitales_codigo_indec", "ext_estadisticas_vitales", ["codigo_indec"])
    op.create_table(
        "ext_fuentes_oficiales_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fuente", sa.String(40), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("filas_leidas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filas_guardadas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("anomalias", sa.JSON),
        sa.Column("mensaje", sa.String(2000)),
        sa.Column("iniciado_at", _TS, nullable=False),
        sa.Column("finalizado_at", _TS),
        sa.Column("disparado_por", sa.String(80)),
    )


def downgrade() -> None:
    op.drop_table("ext_fuentes_oficiales_sync_log")
    op.drop_index("ix_ext_estadisticas_vitales_codigo_indec", table_name="ext_estadisticas_vitales")
    op.drop_table("ext_estadisticas_vitales")
    op.drop_index("ix_ext_equipamientos_tipo_codigo", table_name="ext_equipamientos")
    op.drop_table("ext_equipamientos")
    op.drop_index("ix_ext_renabap_barrios_codigo_indec", table_name="ext_renabap_barrios")
    op.drop_table("ext_renabap_barrios")
    op.drop_table("ext_est_poligonos")
    op.drop_table("ext_est_departamento")
    op.drop_table("ext_est_gobierno_local")
