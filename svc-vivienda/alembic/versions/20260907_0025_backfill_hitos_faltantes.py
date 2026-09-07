"""backfill_hitos_faltantes — completa los 4 hitos de obra en checklists que no los tienen

La migración 0022 sembró la fila de `viv_checklist_tecnico` de las 54 localidades de Cordón
Cuneta directamente (sin pasar por `service._get_or_create_checklist`), por lo que quedaron
**sin filas en `viv_checklist_obra_hitos`**. 0024 solo backfilleó `ch`/`ml` (asumió que `cc`
ya los tenía). Esta migración inserta los 4 tipos (`anticipo`/`40`/`70`/`100`) para cualquier
checklist que tenga menos de 4, en los 3 programas.

Idempotente: solo inserta los tipos que faltan por checklist.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-07
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_HITO_TIPOS = ("anticipo", "40", "70", "100")


def upgrade() -> None:
    conn = op.get_bind()
    existentes = conn.execute(
        sa.text("SELECT checklist_id, tipo FROM viv_checklist_obra_hitos")
    ).fetchall()
    por_checklist: dict[str, set[str]] = {}
    for row in existentes:
        por_checklist.setdefault(row.checklist_id, set()).add(row.tipo)

    checklists = [r.id for r in conn.execute(sa.text("SELECT id FROM viv_checklist_tecnico")).fetchall()]

    hito_tbl = sa.table(
        "viv_checklist_obra_hitos",
        sa.column("id", sa.String()),
        sa.column("checklist_id", sa.String()),
        sa.column("tipo", sa.String()),
    )
    nuevas = [
        {"id": str(uuid.uuid4()), "checklist_id": cid, "tipo": tipo}
        for cid in checklists
        for tipo in _HITO_TIPOS
        if tipo not in por_checklist.get(cid, set())
    ]
    if nuevas:
        conn.execute(hito_tbl.insert(), nuevas)


def downgrade() -> None:
    # No se puede distinguir con seguridad los hitos backfilleados de los creados a mano
    # (todos comparten forma y no llevan fecha). Se dejan — son inertes sin fecha cargada.
    pass
