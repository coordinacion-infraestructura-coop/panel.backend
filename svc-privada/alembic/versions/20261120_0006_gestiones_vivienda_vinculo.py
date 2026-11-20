"""priv_gestiones.vivienda_vinculo — vínculo Vivienda -> Privada en columna propia

docs/files/spec-vinculacion-vivienda-privada.md v1.1.0 §3.3. Hasta ahora el vínculo
se guardaba en `id_legacy`, que el ETL de BigQuery ya había llenado con el id viejo en
todas las gestiones migradas; el sync confundía esos ids con "vinculada a otro caso".
Se copia a la columna nueva lo que ya era un vínculo de Vivienda (`vivienda:%`), sin
tocar `id_legacy`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("priv_gestiones", sa.Column("vivienda_vinculo", sa.String(100), nullable=True))
    op.create_unique_constraint(
        "uq_priv_gestiones_vivienda_vinculo", "priv_gestiones", ["vivienda_vinculo"]
    )
    op.execute(
        "UPDATE priv_gestiones SET vivienda_vinculo = id_legacy "
        "WHERE id_legacy LIKE 'vivienda:%'"
    )


def downgrade() -> None:
    op.drop_constraint("uq_priv_gestiones_vivienda_vinculo", "priv_gestiones", type_="unique")
    op.drop_column("priv_gestiones", "vivienda_vinculo")
