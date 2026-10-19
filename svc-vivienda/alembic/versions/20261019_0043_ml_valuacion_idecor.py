"""Mi Lugar: nomenclaturas catastrales + valuación sugerida desde IDECOR

Dos tablas nuevas (spec-mi-lugar-valor-fiscal-idecor.md §5.2, ADR-031):

- `viv_ml_nomenclaturas`: lista que carga el área por proyecto, con soft delete
  e índice único parcial (proyecto, nomenclatura) entre las activas.
- `viv_ml_valuacion_idecor`: último resultado de la consulta a IDECOR por
  proyecto (valor fiscal sugerido + valor de referencia de mercado). No toca
  `viv_ml_proyectos.valor_fiscal`, que sigue siendo de carga manual.

Sin backfill: la primera corrida del Cloud Scheduler semanal (o el botón
"Recalcular") llena `viv_ml_valuacion_idecor`.

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "viv_ml_nomenclaturas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "proyecto_id", sa.String(36),
            sa.ForeignKey("viv_ml_proyectos.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("nomenclatura", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_ml_nomenclaturas_activas", "viv_ml_nomenclaturas", ["proyecto_id", "nomenclatura"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "viv_ml_valuacion_idecor",
        sa.Column(
            "proyecto_id", sa.String(36),
            sa.ForeignKey("viv_ml_proyectos.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("valor_total", sa.Numeric(18, 2)),
        sa.Column("valor_tierra", sa.Numeric(18, 2)),
        sa.Column("valor_mejoras", sa.Numeric(18, 2)),
        sa.Column("valor_mercado", sa.Numeric(18, 2)),
        sa.Column("mercado_anio", sa.Integer),
        sa.Column("mercado_parcelas_sin_valor", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cant_parcelas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("puntos_sin_parcela", sa.Integer, nullable=False, server_default="0"),
        sa.Column("nomenclaturas_no_encontradas", sa.Text, nullable=False, server_default="[]"),
        sa.Column("vigencia_desde", sa.Date),
        sa.Column("parcelas", sa.Text, nullable=False, server_default="[]"),
        sa.Column("consultado_at", sa.DateTime(timezone=True)),
        sa.Column("ultimo_error", sa.Text),
        sa.Column("ultimo_error_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("viv_ml_valuacion_idecor")
    op.drop_index("uq_ml_nomenclaturas_activas", table_name="viv_ml_nomenclaturas")
    op.drop_table("viv_ml_nomenclaturas")
