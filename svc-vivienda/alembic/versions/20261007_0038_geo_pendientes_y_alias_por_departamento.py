"""Asignación manual de localidades: viv_geo_pendientes + alias por departamento

docs/files/spec-geo-asignacion-manual-localidades.md §3 (ADR-026).

1. `viv_geo_alias_manual` gana `departamento_normalizado` ("" = alias global,
   como todas las filas existentes), baja lógica (`deleted_at`) y
   `propagacion` (de donde sale el "deshacer"). La unicidad pasa de
   `(texto_normalizado)` a `(texto_normalizado, departamento_normalizado)`
   entre filas vigentes.
2. `viv_geo_pendientes`: lo que el resolver no pudo matchear, por fuente.
3. Los "confirmado sin vínculo" de Mi Lugar (loteos nombrados por barrio,
   migración 0036) se acotan al departamento con el que están cargados esos
   proyectos, para que no desvinculen a una localidad homónima de otro
   departamento. Sólo si todos los proyectos con ese nombre comparten un
   único departamento; si no, el alias queda global como estaba.
4. Carga inicial de pendientes de CC/CH/ML (registros activos sin vínculo y
   sin alias). Las demás fuentes se cargan solas en su próxima corrida.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-07
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.geo.matching import normalize_departamento, normalize_name

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_ALIAS_BARRIOS_CREATED_BY = "migracion-confirmado-sin-vinculo"

# (tabla, columna del nombre, origen)
_TABLAS = [
    ("viv_cordon_cuneta", "municipio", "cordon_cuneta"),
    ("viv_cordoba_hogar", "localidad", "cordoba_hogar"),
    ("viv_ml_proyectos", "localidad_nombre", "mi_lugar"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. viv_geo_alias_manual ──────────────────────────────────────────────
    op.add_column(
        "viv_geo_alias_manual",
        sa.Column("departamento_normalizado", sa.String(200), nullable=False, server_default=""),
    )
    op.add_column("viv_geo_alias_manual", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("viv_geo_alias_manual", sa.Column("updated_by", sa.String(200), nullable=True))
    op.add_column("viv_geo_alias_manual", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("viv_geo_alias_manual", sa.Column("propagacion", sa.Text(), nullable=True))
    op.drop_constraint("uq_geo_alias_manual_texto_normalizado", "viv_geo_alias_manual", type_="unique")
    op.create_index(
        "uq_geo_alias_manual_texto_departamento",
        "viv_geo_alias_manual",
        ["texto_normalizado", "departamento_normalizado"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── 2. viv_geo_pendientes ────────────────────────────────────────────────
    op.create_table(
        "viv_geo_pendientes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("origen", sa.String(50), nullable=False),
        sa.Column("departamento_original", sa.String(200), nullable=True),
        sa.Column("localidad_original", sa.String(200), nullable=False),
        sa.Column("departamento_normalizado", sa.String(200), nullable=False, server_default=""),
        sa.Column("texto_normalizado", sa.String(200), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=True),
        sa.Column("primera_vez", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultima_vez", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("alias_id", sa.String(36), nullable=True),
        sa.Column("resuelta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resuelta_by", sa.String(200), nullable=True),
        sa.ForeignKeyConstraint(["alias_id"], ["viv_geo_alias_manual.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "estado IN ('pendiente','resuelta','descartada')", name="ck_geo_pendientes_estado"
        ),
    )
    op.create_index(
        "uq_geo_pendientes_origen_departamento_texto",
        "viv_geo_pendientes",
        ["origen", "departamento_normalizado", "texto_normalizado"],
        unique=True,
    )

    # ── 3. Acotar por departamento los barrios de Mi Lugar ───────────────────
    proyectos = conn.execute(sa.text(
        "SELECT localidad_nombre, departamento FROM viv_ml_proyectos WHERE deleted_at IS NULL"
    )).fetchall()
    for alias_id, texto in conn.execute(
        sa.text(
            "SELECT id, texto_normalizado FROM viv_geo_alias_manual "
            "WHERE created_by = :cb AND origen = 'mi_lugar' AND id_geo IS NULL"
        ),
        {"cb": _ALIAS_BARRIOS_CREATED_BY},
    ).fetchall():
        departamentos = {
            normalize_departamento(dep) for nombre, dep in proyectos if normalize_name(nombre) == texto
        }
        if len(departamentos) == 1 and "" not in departamentos:
            conn.execute(
                sa.text("UPDATE viv_geo_alias_manual SET departamento_normalizado = :dep WHERE id = :id"),
                {"dep": departamentos.pop(), "id": alias_id},
            )

    # ── 4. Carga inicial de pendientes de CC / CH / ML ───────────────────────
    alias = {
        (texto, dep)
        for texto, dep in conn.execute(sa.text(
            "SELECT texto_normalizado, departamento_normalizado FROM viv_geo_alias_manual "
            "WHERE deleted_at IS NULL"
        )).fetchall()
    }
    pendientes_tbl = sa.table(
        "viv_geo_pendientes",
        sa.column("id", sa.String()),
        sa.column("origen", sa.String()),
        sa.column("departamento_original", sa.String()),
        sa.column("localidad_original", sa.String()),
        sa.column("departamento_normalizado", sa.String()),
        sa.column("texto_normalizado", sa.String()),
        sa.column("cantidad", sa.Integer()),
        sa.column("primera_vez", sa.DateTime(timezone=True)),
        sa.column("ultima_vez", sa.DateTime(timezone=True)),
        sa.column("estado", sa.String()),
    )
    now = datetime.now(timezone.utc)
    nuevos: dict[tuple[str, str, str], dict] = {}
    for tabla, col, origen in _TABLAS:
        for nombre, departamento in conn.execute(sa.text(
            f"SELECT {col}, departamento FROM {tabla} WHERE deleted_at IS NULL AND localidad_id IS NULL"
        )).fetchall():
            texto, dep = normalize_name(nombre), normalize_departamento(departamento)
            if not texto or (texto, dep) in alias or (texto, "") in alias:
                continue
            fila = nuevos.setdefault((origen, dep, texto), {
                "id": str(uuid.uuid4()), "origen": origen,
                "departamento_original": departamento, "localidad_original": nombre,
                "departamento_normalizado": dep, "texto_normalizado": texto,
                "cantidad": 0, "primera_vez": now, "ultima_vez": now, "estado": "pendiente",
            })
            fila["cantidad"] += 1
    if nuevos:
        op.bulk_insert(pendientes_tbl, list(nuevos.values()))


def downgrade() -> None:
    conn = op.get_bind()
    op.drop_index("uq_geo_pendientes_origen_departamento_texto", table_name="viv_geo_pendientes")
    op.drop_table("viv_geo_pendientes")

    # Los alias dados de baja no existen en el esquema anterior. Si quedaron dos
    # alias vigentes con el mismo texto en departamentos distintos, la unicidad
    # vieja no se puede recrear: hay que resolverlo a mano antes del downgrade.
    conn.execute(sa.text("DELETE FROM viv_geo_alias_manual WHERE deleted_at IS NOT NULL"))
    op.drop_index("uq_geo_alias_manual_texto_departamento", table_name="viv_geo_alias_manual")
    op.create_unique_constraint(
        "uq_geo_alias_manual_texto_normalizado", "viv_geo_alias_manual", ["texto_normalizado"]
    )
    for col in ("propagacion", "deleted_at", "updated_by", "updated_at", "departamento_normalizado"):
        op.drop_column("viv_geo_alias_manual", col)
