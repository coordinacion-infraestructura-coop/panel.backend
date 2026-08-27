"""checklist_tecnico_dgv — panel editable de checklist por localidad y programa (CC/CH/ML)

Ancla a las entidades ya existentes (viv_cordon_cuneta / viv_cordoba_hogar / viv_ml_proyectos) en
vez de duplicar localidad/expediente/monto. Incluye backfill de una sola vez desde el sync de Excel
de Cordón Cuneta (viv_cc_checklist_tecnico/items, que sigue corriendo sin cambios) para que esas 54
localidades no arranquen en blanco.

Ver docs/files/spec-checklist-tecnico-dgv.md (approved 2026-08-26).

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-26
"""
from __future__ import annotations

import unicodedata
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


# ── Catálogo: Estado del expediente (7 valores, confirmados con el área — solapa "Validaciones") ──
_ESTADO_EXPEDIENTE_SEED = [
    {"id": 1, "label": "A INICIAR en DGV", "orden": 0},
    {"id": 2, "label": "En CURSO en DGV", "orden": 1},
    {"id": 3, "label": "COMPLETO en DGV", "orden": 2},
    {"id": 4, "label": "En CURSO en TC", "orden": 3},
    {"id": 5, "label": "APROBADO por TC", "orden": 4},
    {"id": 6, "label": "OBRA en EJECUCIÓN", "orden": 5},
    {"id": 7, "label": "OBRA TERMINADA", "orden": 6},
]

# ── Catálogo: Repartición — 3 valores de ejemplo, administrable, se completa en el backfill ──
_REPARTICION_SEED = [
    {"id": 1, "programa": None, "label": "Dirección de Regularización de Obras y Proyectos", "orden": 0},
    {"id": 2, "programa": None, "label": "Dirección Legal y Notarial", "orden": 1},
    {"id": 3, "programa": None, "label": "Área Coordinación Administrativa", "orden": 2},
]

# ── Ítems de Cordón Cuneta: el sync de Excel numera los 19 en una secuencia plana (1-19, ver
# spec-sync-cc-checklist-tecnico.md §3.1); el panel nuevo usa 9 ítems top-level + el ítem 4 abierto
# en 10 sub-ítems (spec-checklist-tecnico-dgv.md §4). Mapeo sync_item_num -> (item_num, sub_item_num).
_CC_ITEM_MAP = {
    1: (1, None), 2: (2, None), 3: (3, None), 4: (4, None),
    5: (4, 1), 6: (4, 2), 7: (4, 3), 8: (4, 4), 9: (4, 5),
    10: (4, 6), 11: (4, 7), 12: (4, 8), 13: (4, 9), 14: (4, 10),
    15: (5, None), 16: (6, None), 17: (7, None), 18: (8, None), 19: (9, None),
}


def _normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(sin_acentos.strip().lower().split())


_VALOR_ITEM_MAP = {
    "sin presentar": "sin_presentar",
    "a corregir por m/c": "a_corregir",
    "en evaluacion tecnica": "eval_tecnica",
    "en evaluacion juridico": "eval_juridica",
    "en evaluacion juridica": "eval_juridica",
    "completo ok": "completo",
}


def upgrade() -> None:
    # ── viv_checklist_estado_expediente ──────────────────────────────────────
    op.create_table(
        "viv_checklist_estado_expediente",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── viv_checklist_reparticion ─────────────────────────────────────────────
    op.create_table(
        "viv_checklist_reparticion",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("programa", sa.String(2), nullable=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── viv_checklist_tecnico ─────────────────────────────────────────────────
    op.create_table(
        "viv_checklist_tecnico",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("programa", sa.String(2), nullable=False),
        sa.Column("entidad_id", sa.String(36), nullable=False),
        sa.Column("estado_expediente_id", sa.BigInteger(), sa.ForeignKey("viv_checklist_estado_expediente.id")),
        sa.Column("fecha_radicacion", sa.Date()),
        sa.Column("reparticion_id", sa.BigInteger(), sa.ForeignKey("viv_checklist_reparticion.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("updated_by", sa.String(200)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("programa", "entidad_id", name="uq_checklist_programa_entidad"),
    )

    # ── viv_checklist_items ───────────────────────────────────────────────────
    op.create_table(
        "viv_checklist_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "checklist_id",
            sa.String(36),
            sa.ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_num", sa.SmallInteger(), nullable=False),
        sa.Column("sub_item_num", sa.SmallInteger()),
        sa.Column("valor", sa.String(30), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checklist_id", "item_num", "sub_item_num", name="uq_checklist_item"),
    )

    # ── viv_checklist_obra_hitos (solo programa='cc' en esta entrega) ────────
    op.create_table(
        "viv_checklist_obra_hitos",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "checklist_id",
            sa.String(36),
            sa.ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("fecha_acreditado", sa.Date()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checklist_id", "tipo", name="uq_checklist_hito"),
    )

    # ── Seed de catálogos ──────────────────────────────────────────────────────
    estado_tbl = sa.table(
        "viv_checklist_estado_expediente",
        sa.column("id", sa.BigInteger()),
        sa.column("label", sa.String()),
        sa.column("orden", sa.Integer()),
    )
    op.bulk_insert(estado_tbl, _ESTADO_EXPEDIENTE_SEED)

    reparticion_tbl = sa.table(
        "viv_checklist_reparticion",
        sa.column("id", sa.BigInteger()),
        sa.column("programa", sa.String()),
        sa.column("label", sa.String()),
        sa.column("orden", sa.Integer()),
    )
    op.bulk_insert(reparticion_tbl, _REPARTICION_SEED)

    # ── Backfill: última data del sync de Excel de CC → tablas nuevas (una sola vez) ─────────────
    conn = op.get_bind()

    estado_por_label_normalizado = {_normalizar(e["label"]): e["id"] for e in _ESTADO_EXPEDIENTE_SEED}
    reparticion_por_label_normalizado = {_normalizar(r["label"]): r["id"] for r in _REPARTICION_SEED}
    siguiente_reparticion_id = max(r["id"] for r in _REPARTICION_SEED) + 1

    def resolver_reparticion(raw_label: str | None) -> int | None:
        nonlocal siguiente_reparticion_id
        norm = _normalizar(raw_label)
        if not norm or norm == "_":
            return None
        if norm in reparticion_por_label_normalizado:
            return reparticion_por_label_normalizado[norm]
        nuevo_id = siguiente_reparticion_id
        siguiente_reparticion_id += 1
        conn.execute(
            reparticion_tbl.insert().values(
                id=nuevo_id, programa=None, label=raw_label.strip(), orden=100 + nuevo_id
            )
        )
        reparticion_por_label_normalizado[norm] = nuevo_id
        return nuevo_id

    sync_checklists = conn.execute(
        sa.text(
            "SELECT id, municipio_id, estado_expediente, fecha_radicacion, reparticion "
            "FROM viv_cc_checklist_tecnico WHERE municipio_id IS NOT NULL"
        )
    ).fetchall()

    checklist_tbl = sa.table(
        "viv_checklist_tecnico",
        sa.column("id", sa.String()),
        sa.column("programa", sa.String()),
        sa.column("entidad_id", sa.String()),
        sa.column("estado_expediente_id", sa.BigInteger()),
        sa.column("fecha_radicacion", sa.Date()),
        sa.column("reparticion_id", sa.BigInteger()),
    )
    items_tbl = sa.table(
        "viv_checklist_items",
        sa.column("id", sa.String()),
        sa.column("checklist_id", sa.String()),
        sa.column("item_num", sa.SmallInteger()),
        sa.column("sub_item_num", sa.SmallInteger()),
        sa.column("valor", sa.String()),
    )

    for sync_row in sync_checklists:
        nuevo_checklist_id = str(uuid.uuid4())
        conn.execute(
            checklist_tbl.insert().values(
                id=nuevo_checklist_id,
                programa="cc",
                entidad_id=sync_row.municipio_id,
                estado_expediente_id=estado_por_label_normalizado.get(_normalizar(sync_row.estado_expediente)),
                fecha_radicacion=sync_row.fecha_radicacion,
                reparticion_id=resolver_reparticion(sync_row.reparticion),
            )
        )

        sync_items = conn.execute(
            sa.text("SELECT item_num, valor FROM viv_cc_checklist_items WHERE checklist_id = :cid"),
            {"cid": sync_row.id},
        ).fetchall()
        nuevas_filas_items = []
        for sync_item in sync_items:
            mapeo = _CC_ITEM_MAP.get(sync_item.item_num)
            if mapeo is None:
                continue
            item_num, sub_item_num = mapeo
            valor = _VALOR_ITEM_MAP.get(_normalizar(sync_item.valor), "sin_presentar")
            nuevas_filas_items.append(
                {
                    "id": str(uuid.uuid4()),
                    "checklist_id": nuevo_checklist_id,
                    "item_num": item_num,
                    "sub_item_num": sub_item_num,
                    "valor": valor,
                }
            )
        if nuevas_filas_items:
            conn.execute(items_tbl.insert(), nuevas_filas_items)


def downgrade() -> None:
    op.drop_table("viv_checklist_obra_hitos")
    op.drop_table("viv_checklist_items")
    op.drop_table("viv_checklist_tecnico")
    op.drop_table("viv_checklist_reparticion")
    op.drop_table("viv_checklist_estado_expediente")
