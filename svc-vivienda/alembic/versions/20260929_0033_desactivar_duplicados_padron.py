"""Desactivar 7 filas duplicadas dentro del propio padrón viv_geo_localidades

Encontradas investigando los casos residuales sin resolver (migración 0032)
y confirmadas por el usuario como la misma localidad real (coordenadas a
metros/pocos km entre sí). No se borran — quedan con `activo=false` para no
romper ninguna referencia histórica — pero dejan de indexarse para matching
(`app/geo/service.py::_cargar_padron` sólo considera filas activas), lo que
además resuelve la ambigüedad que traía "sin_match" a ATP/Gasífera para "La
Higuera", "Los Pozos" y "La Tordilla" sin necesitar alias nuevos.

Verificado antes de desactivar: ninguna fila de CC/CH/ML/viv_geo_alias_manual/
gas_pit_acciones_territorio/gas_pit_obras_localidades/atp_compromisos
referencia ninguno de los 7 id_geo perdedores — no hace falta repuntar nada.

| Localidad (queda activa)      | id_geo activo | Localidad (se desactiva)              | id_geo desactivado | Depto |
|--------------------------------|---------------|----------------------------------------|---------------------|-------|
| CHARBONIER                     | 141           | Charbonier (texto idéntico)             | 555                 | Punilla |
| La Higuera                     | 533           | HIGUERAS (la Higuera)                   | 43                  | Cruz del Eje |
| LOS POZOS                      | 77            | LOS POZOS (KM. 827)                     | 81                  | Ischilín |
| LA TORDILLA                    | 298           | LA TORDILLA (Colonia la Tordilla)       | 285                 | San Justo |
| Cañada de Río Pinto             | 551           | CAÑADA DE RIO PINTO (la Verde)          | 78                  | Ischilín |
| GUTEMBERG                      | 469           | SAN PEDRO (Gutemberg)                   | 213                 | Río Seco |
| Eufrasio Loza                  | 558           | EUFRASIO LOZA - CAND. NORTE             | 212                 | Río Seco |

ADR-024 / docs/files/spec-normalizacion-localidades.md

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

_DESACTIVAR = ("555", "43", "81", "285", "78", "213", "212")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE viv_geo_localidades SET activo = false WHERE id_geo = ANY(:ids)"),
        {"ids": list(_DESACTIVAR)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE viv_geo_localidades SET activo = true WHERE id_geo = ANY(:ids)"),
        {"ids": list(_DESACTIVAR)},
    )
