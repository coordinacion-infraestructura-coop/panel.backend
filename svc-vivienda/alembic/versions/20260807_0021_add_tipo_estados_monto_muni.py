"""add tipo to ml_estados and monto_por_lote_muni to config

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

# 14 estados CC, usados como catálogo inicial para muni y prov
_CC_LABELS = [
    {"label": "Sin Iniciar",                                    "bg": "#ECEFF1", "text_color": "#455A64", "orden": 0},
    {"label": "Sin Exp de Gobierno",                            "bg": "#FFF3CD", "text_color": "#856404", "orden": 1},
    {"label": "Notificado",                                     "bg": "#DBEAFE", "text_color": "#1E40AF", "orden": 2},
    {"label": "A la espera de Documentacion",                   "bg": "#FFE5D0", "text_color": "#8B3A00", "orden": 3},
    {"label": "En revision tecnica",                            "bg": "#C8E6C9", "text_color": "#1B5E20", "orden": 4},
    {"label": "En Correccion",                                  "bg": "#EDE7F6", "text_color": "#4527A0", "orden": 5},
    {"label": "Documentacion Completada",                       "bg": "#E0F2F1", "text_color": "#00695C", "orden": 6},
    {"label": "Legales para convenio",                          "bg": "#D4EDDA", "text_color": "#155724", "orden": 7},
    {"label": "Administracion para NP",                         "bg": "#FCE4EC", "text_color": "#880E4F", "orden": 8},
    {"label": "Convenio Firmado",                               "bg": "#E0F7FA", "text_color": "#006064", "orden": 9},
    {"label": "Legales para Proyecto de Dictamen y Resolucion", "bg": "#E8EAF6", "text_color": "#1A237E", "orden": 10},
    {"label": "Legales del MCyM",                               "bg": "#ECEFF1", "text_color": "#455A64", "orden": 11},
    {"label": "Administracion OC",                              "bg": "#ECEFF1", "text_color": "#455A64", "orden": 12},
    {"label": "TC",                                             "bg": "#ECEFF1", "text_color": "#455A64", "orden": 13},
]


def upgrade() -> None:
    # ── 1. Agregar columna tipo a viv_ml_estados ──────────────────────────────
    op.add_column(
        "viv_ml_estados",
        sa.Column("tipo", sa.String(10), server_default="exp", nullable=False),
    )

    # ── 2. Seed estados para muni (IDs 1001-1014) y prov (IDs 2001-2014) ─────
    estados_tbl = sa.table(
        "viv_ml_estados",
        sa.column("id", sa.BigInteger()),
        sa.column("label", sa.String()),
        sa.column("bg", sa.String()),
        sa.column("text_color", sa.String()),
        sa.column("orden", sa.Integer()),
        sa.column("tipo", sa.String()),
        sa.column("aplica_juridico", sa.Boolean()),
        sa.column("aplica_tecnico", sa.Boolean()),
        sa.column("aplica_financiero", sa.Boolean()),
    )
    muni_rows = [
        {"id": 1001 + i, "tipo": "muni", "aplica_juridico": True, "aplica_tecnico": True, "aplica_financiero": True, **row}
        for i, row in enumerate(_CC_LABELS)
    ]
    prov_rows = [
        {"id": 2001 + i, "tipo": "prov", "aplica_juridico": True, "aplica_tecnico": True, "aplica_financiero": True, **row}
        for i, row in enumerate(_CC_LABELS)
    ]
    op.bulk_insert(estados_tbl, muni_rows + prov_rows)

    # ── 3. Agregar monto_por_lote_muni a viv_ml_config ───────────────────────
    op.add_column(
        "viv_ml_config",
        sa.Column("monto_por_lote_muni", sa.Numeric(18, 2), server_default="14000000", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("viv_ml_config", "monto_por_lote_muni")
    op.execute("DELETE FROM viv_ml_estados WHERE tipo IN ('muni', 'prov')")
    op.drop_column("viv_ml_estados", "tipo")
