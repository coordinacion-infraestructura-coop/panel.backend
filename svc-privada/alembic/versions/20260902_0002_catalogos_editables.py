"""catálogos editables + campos de mejora en priv_gestiones (E1/E2)

spec-privada-categorias-programas.md (approved) / ADR-010.

- priv_categorias / priv_programas / priv_areas — 3 catálogos editables independientes
  (patrón viv_cc_estados: id bigint client-gen, label, orden, activo).
- priv_gestiones += categoria_id / programa_id / area_id (FK nullable),
  ok_gobernador / ok_ministro (VARCHAR(20) CHECK, default 'PENDIENTE'),
  acciones_implementadas (Text) — E2 lo persiste en la gestión, no sólo en el evento.
- Seed de las 9 categorías + arranque de programas/áreas. El backfill de `categoria_id` y
  `acciones_implementadas` desde datos existentes lo hace `scripts/backfill_categorias.py`
  (re-ejecutable, para la doble corrida + diff de RE-1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_OK_VALS = ("SI", "NO", "PENDIENTE")
_OK_SQL = ", ".join(f"'{v}'" for v in _OK_VALS)

# 9 categorías pedidas (2026-08-31). id = epoch-ms fijo para que el seed sea idempotente
# y reproducible. orden 10..90. Colores por defecto (editables en runtime).
_CATEGORIAS = [
    (1756700000001, "Vivienda", 10, "#dbeafe", "#1e40af"),
    (1756700000002, "Loteos", 20, "#dcfce7", "#166534"),
    (1756700000003, "Cordón Cuneta y adoquinado", 30, "#fef9c3", "#854d0e"),
    (1756700000004, "Pedidos por ATP", 40, "#fae8ff", "#86198f"),
    (1756700000005, "Pedidos NorOeste y Sur Sur", 50, "#e0e7ff", "#3730a3"),
    (1756700000006, "Obras de Recursos Hídricos", 60, "#cffafe", "#155e75"),
    (1756700000007, "Pedidos Administrativos", 70, "#f1f5f9", "#334155"),
    (1756700000008, "Otras Obras", 80, "#ffedd5", "#9a3412"),
    (1756700000009, "Ayudas a instituciones", 90, "#fee2e2", "#991b1b"),
]

# Arranque de programas — ampliable desde el panel de administración.
_PROGRAMAS = [
    (1756700001001, "Córdoba Hogar", "CORDOBA_HOGAR", 10),
    (1756700001002, "Mi Lugar", "MI_LUGAR", 20),
    (1756700001003, "Cordón Cuneta", "CORDON_CUNETA", 30),
]

# Arranque de áreas (D-2: se completará híbrido con el relevamiento). Incluye el
# centinela para el backfill del DAG (E3).
_AREAS = [
    (1756700002001, "DGV", 10, False),
    (1756700002002, "Secretaría de Gestión y Vinculación de Infraestructura", 20, False),
    (1756700002999, "Área desconocida", 999, True),
]


def upgrade() -> None:
    for tbl, extra in (
        ("priv_categorias", [
            sa.Column("bg", sa.String(10)),
            sa.Column("text_color", sa.String(10)),
        ]),
        ("priv_programas", [sa.Column("codigo", sa.String(60), unique=True)]),
        ("priv_areas", [sa.Column("es_centinela", sa.Boolean(), nullable=False, server_default="false")]),
    ):
        op.create_table(
            tbl,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
            sa.Column("label", sa.String(200), nullable=False),
            sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
            *extra,
        )

    op.bulk_insert(
        sa.table(
            "priv_categorias",
            sa.column("id", sa.BigInteger), sa.column("label", sa.String),
            sa.column("orden", sa.Integer), sa.column("bg", sa.String), sa.column("text_color", sa.String),
        ),
        [{"id": i, "label": l, "orden": o, "bg": bg, "text_color": tc} for i, l, o, bg, tc in _CATEGORIAS],
    )
    op.bulk_insert(
        sa.table(
            "priv_programas",
            sa.column("id", sa.BigInteger), sa.column("label", sa.String),
            sa.column("codigo", sa.String), sa.column("orden", sa.Integer),
        ),
        [{"id": i, "label": l, "codigo": c, "orden": o} for i, l, c, o in _PROGRAMAS],
    )
    op.bulk_insert(
        sa.table(
            "priv_areas",
            sa.column("id", sa.BigInteger), sa.column("label", sa.String),
            sa.column("orden", sa.Integer), sa.column("es_centinela", sa.Boolean),
        ),
        [{"id": i, "label": l, "orden": o, "es_centinela": s} for i, l, o, s in _AREAS],
    )

    with op.batch_alter_table("priv_gestiones") as b:
        b.add_column(sa.Column("categoria_id", sa.BigInteger(), sa.ForeignKey("priv_categorias.id")))
        b.add_column(sa.Column("programa_id", sa.BigInteger(), sa.ForeignKey("priv_programas.id")))
        b.add_column(sa.Column("area_id", sa.BigInteger(), sa.ForeignKey("priv_areas.id")))
        b.add_column(sa.Column("ok_gobernador", sa.String(20), nullable=False, server_default="PENDIENTE"))
        b.add_column(sa.Column("ok_ministro", sa.String(20), nullable=False, server_default="PENDIENTE"))
        b.add_column(sa.Column("acciones_implementadas", sa.Text()))
    op.create_check_constraint("ck_priv_gestiones_ok_gob", "priv_gestiones", f"ok_gobernador IN ({_OK_SQL})")
    op.create_check_constraint("ck_priv_gestiones_ok_min", "priv_gestiones", f"ok_ministro IN ({_OK_SQL})")


def downgrade() -> None:
    op.drop_constraint("ck_priv_gestiones_ok_min", "priv_gestiones")
    op.drop_constraint("ck_priv_gestiones_ok_gob", "priv_gestiones")
    with op.batch_alter_table("priv_gestiones") as b:
        for col in ("acciones_implementadas", "ok_ministro", "ok_gobernador", "area_id", "programa_id", "categoria_id"):
            b.drop_column(col)
    op.drop_table("priv_areas")
    op.drop_table("priv_programas")
    op.drop_table("priv_categorias")
