"""dgv_correcciones_area_tecnica — correcciones del área técnica DGV (2026-09)

1. Catálogo "Estado del expediente" (viv_checklist_estado_expediente): renombra
   `... en DGV` → `... en TÉCNICA` y `... TC` → `... TRIB.C`, reordena, y agrega
   `RECHAZADO por M/C` y `SIN AUTORIZACION MIN.GOB` (7 → 9 valores). Relabel in place para
   preservar los `estado_expediente_id` ya referenciados por `viv_checklist_tecnico`.
2. "Estado de la documentación" pasa de enum fijo (`viv_checklist_items.valor`) a catálogo
   administrable: nueva tabla `viv_checklist_item_estado` (5 valores + color + `es_completo`),
   y `viv_checklist_items.valor` (str) → `item_estado_id` (FK).
3. `viv_checklist_tecnico.obs_obra` — observaciones de la etapa de obra (columna AT del Excel),
   separadas de las observaciones del expediente.
4. Hitos de obra para los 3 programas: crea las 4 filas de hito faltantes en las filas de
   `viv_checklist_tecnico` de `ch`/`ml` ya existentes (las de `cc` ya las tienen).

Fuente: docs/context/areas/secretaria_Vivienda/obervaciones AREA TECNICA.pdf +
`DGV Programas 2026.xlsx` solapa `Validaciones` (filas 403-418).
Ver docs/files/spec-checklist-tecnico-dgv.md v1.2.0.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-07
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


# id → (label nuevo, orden nuevo). ids 1-7 ya existen (relabel in place); 8 y 9 son nuevos.
_ESTADO_EXP_NUEVO: dict[int, tuple[str, int]] = {
    1: ("A ESPERA de DOC.TÉCNICA", 0),
    8: ("RECHAZADO por M/C", 1),
    9: ("SIN AUTORIZACION MIN.GOB", 2),
    2: ("En CURSO en TÉCNICA", 3),
    3: ("COMPLETO en TÉCNICA", 4),
    4: ("En CURSO en TRIB.C", 5),
    5: ("APROBADO por TRIB.C", 6),
    6: ("OBRA en EJECUCIÓN", 7),
    7: ("OBRA TERMINADA", 8),
}
_ESTADO_EXP_VIEJO: dict[int, tuple[str, int]] = {
    1: ("A INICIAR en DGV", 0),
    2: ("En CURSO en DGV", 1),
    3: ("COMPLETO en DGV", 2),
    4: ("En CURSO en TC", 3),
    5: ("APROBADO por TC", 4),
    6: ("OBRA en EJECUCIÓN", 5),
    7: ("OBRA TERMINADA", 6),
}

# viv_checklist_item_estado seed. Labels de `Validaciones!A403-407`; colores de STATUS_META
# del frontend (ChecklistTecnicoPage.tsx).
_ITEM_ESTADO_SEED = [
    {"id": 1, "label": "A ESPERA de DOC.TÉCNICA", "orden": 0, "bg": "#f1f5f9", "text_color": "#64748b", "es_completo": False},
    {"id": 2, "label": "DIR. JUR. LEGAL Y NOTARIAL", "orden": 1, "bg": "#e0e7ff", "text_color": "#4338ca", "es_completo": False},
    {"id": 3, "label": "En Evaluación TÉCNICA", "orden": 2, "bg": "#dbeafe", "text_color": "#1e40af", "es_completo": False},
    {"id": 4, "label": "A corregir por M/C", "orden": 3, "bg": "#fef3c7", "text_color": "#92400e", "es_completo": False},
    {"id": 5, "label": "Completo OK", "orden": 4, "bg": "#dcfce7", "text_color": "#166534", "es_completo": True},
]

# valor viejo (enum) → id nuevo en viv_checklist_item_estado
_VALOR_A_ID = {
    "sin_presentar": 1,
    "eval_juridica": 2,
    "eval_tecnica": 3,
    "a_corregir": 4,
    "completo": 5,
}
_ID_A_VALOR = {v: k for k, v in _VALOR_A_ID.items()}

_HITO_TIPOS = ("anticipo", "40", "70", "100")


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Estado del expediente: relabel + reorder + 2 nuevos ──────────────────
    estado_tbl = sa.table(
        "viv_checklist_estado_expediente",
        sa.column("id", sa.BigInteger()),
        sa.column("label", sa.String()),
        sa.column("orden", sa.Integer()),
        sa.column("activo", sa.Boolean()),
    )
    for _id, (label, orden) in _ESTADO_EXP_NUEVO.items():
        if _id in (8, 9):
            conn.execute(estado_tbl.insert().values(id=_id, label=label, orden=orden, activo=True))
        else:
            conn.execute(estado_tbl.update().where(estado_tbl.c.id == _id).values(label=label, orden=orden))

    # ── 2. viv_checklist_item_estado + migración de viv_checklist_items.valor ───
    op.create_table(
        "viv_checklist_item_estado",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("bg", sa.String(10), server_default="#f1f5f9", nullable=False),
        sa.Column("text_color", sa.String(10), server_default="#64748b", nullable=False),
        sa.Column("es_completo", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    item_estado_tbl = sa.table(
        "viv_checklist_item_estado",
        sa.column("id", sa.BigInteger()),
        sa.column("label", sa.String()),
        sa.column("orden", sa.Integer()),
        sa.column("bg", sa.String()),
        sa.column("text_color", sa.String()),
        sa.column("es_completo", sa.Boolean()),
    )
    op.bulk_insert(item_estado_tbl, _ITEM_ESTADO_SEED)

    op.add_column(
        "viv_checklist_items",
        sa.Column(
            "item_estado_id",
            sa.BigInteger(),
            sa.ForeignKey("viv_checklist_item_estado.id"),
            nullable=True,
        ),
    )
    for valor, new_id in _VALOR_A_ID.items():
        conn.execute(
            sa.text("UPDATE viv_checklist_items SET item_estado_id = :nid WHERE valor = :v"),
            {"nid": new_id, "v": valor},
        )
    conn.execute(sa.text("UPDATE viv_checklist_items SET item_estado_id = 1 WHERE item_estado_id IS NULL"))
    op.alter_column("viv_checklist_items", "item_estado_id", nullable=False)
    op.drop_column("viv_checklist_items", "valor")

    # ── 3. obs_obra ───────────────────────────────────────────────────────────
    op.add_column("viv_checklist_tecnico", sa.Column("obs_obra", sa.Text(), nullable=True))

    # ── 4. Hitos de obra para las filas ch/ml ya existentes ───────────────────
    filas = conn.execute(
        sa.text(
            "SELECT id FROM viv_checklist_tecnico WHERE programa IN ('ch','ml') "
            "AND id NOT IN (SELECT DISTINCT checklist_id FROM viv_checklist_obra_hitos)"
        )
    ).fetchall()
    hito_tbl = sa.table(
        "viv_checklist_obra_hitos",
        sa.column("id", sa.String()),
        sa.column("checklist_id", sa.String()),
        sa.column("tipo", sa.String()),
    )
    nuevas = [
        {"id": str(uuid.uuid4()), "checklist_id": row.id, "tipo": tipo}
        for row in filas
        for tipo in _HITO_TIPOS
    ]
    if nuevas:
        conn.execute(hito_tbl.insert(), nuevas)


def downgrade() -> None:
    conn = op.get_bind()

    # 4. Los hitos backfill de ch/ml no se pueden distinguir con seguridad de los cargados a
    #    mano → se dejan (son inertes si el frontend vuelve a ocultarlos).

    # 3. obs_obra
    op.drop_column("viv_checklist_tecnico", "obs_obra")

    # 2. valor <- item_estado_id
    op.add_column("viv_checklist_items", sa.Column("valor", sa.String(30), nullable=True))
    for new_id, valor in _ID_A_VALOR.items():
        conn.execute(
            sa.text("UPDATE viv_checklist_items SET valor = :v WHERE item_estado_id = :nid"),
            {"v": valor, "nid": new_id},
        )
    conn.execute(sa.text("UPDATE viv_checklist_items SET valor = 'sin_presentar' WHERE valor IS NULL"))
    op.alter_column("viv_checklist_items", "valor", nullable=False)
    op.drop_column("viv_checklist_items", "item_estado_id")
    op.drop_table("viv_checklist_item_estado")

    # 1. estado del expediente
    estado_tbl = sa.table(
        "viv_checklist_estado_expediente",
        sa.column("id", sa.BigInteger()),
        sa.column("label", sa.String()),
        sa.column("orden", sa.Integer()),
    )
    conn.execute(estado_tbl.delete().where(estado_tbl.c.id.in_([8, 9])))
    for _id, (label, orden) in _ESTADO_EXP_VIEJO.items():
        conn.execute(estado_tbl.update().where(estado_tbl.c.id == _id).values(label=label, orden=orden))
