"""Tablero analítico de Vivienda: KPIs por snapshot + área responsable de cada estado

docs/files/spec-vivienda-tablero-analitico.md v1.0.0 (pedidos del área de Vivienda, 2026-10-02).

1. `viv_resumen_territorial_snapshot.kpis` (JSON NULL): KPIs por área precalculados al guardar
   cada snapshot — la serie histórica de la pestaña Tendencias. La historia previa se completa
   aparte con `scripts/backfill_kpis_snapshot.py` (un snapshot por día), no acá: el cálculo
   vive en código de la app y una migración no debe depender de él.
2. `area_responsable` (VARCHAR(20) NULL + CHECK) en `viv_cc_estados`, `viv_ch_estados` y
   `viv_ml_estados`: qué área lleva cada estado. Sin precarga — lo asigna el área desde la UI.

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

_TABLAS_ESTADO = ("viv_cc_estados", "viv_ch_estados", "viv_ml_estados")
_AREAS = "('juridica', 'tecnica', 'financiera', 'externa')"


def upgrade() -> None:
    op.add_column("viv_resumen_territorial_snapshot", sa.Column("kpis", sa.JSON(), nullable=True))

    for tabla in _TABLAS_ESTADO:
        op.add_column(tabla, sa.Column("area_responsable", sa.String(20), nullable=True))
        op.create_check_constraint(
            f"ck_{tabla}_area_responsable",
            tabla,
            f"area_responsable IS NULL OR area_responsable IN {_AREAS}",
        )


def downgrade() -> None:
    for tabla in _TABLAS_ESTADO:
        op.drop_constraint(f"ck_{tabla}_area_responsable", tabla, type_="check")
        op.drop_column(tabla, "area_responsable")
    op.drop_column("viv_resumen_territorial_snapshot", "kpis")
