"""Unify CC and CH estado catalogs to the standard 15-state workflow

Revision ID: 0009
Revises: 0008
"""

import time

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    now_ms = int(time.time() * 1000)

    # ─── CC: Add "Para Notificar" + fix orden + rename "Legales para convenio" ─

    # Shift all CC states with orden >= 2 up by 1 to make room for the new state
    conn.execute(sa.text("UPDATE viv_cc_estados SET orden = orden + 1 WHERE orden >= 2"))

    # Insert "Para Notificar" at orden=2 (between "Sin Exp de Gobierno" and "Notificado")
    conn.execute(
        sa.text("""
            INSERT INTO viv_cc_estados
                (id, label, bg, text_color, orden, aplica_juridico, aplica_tecnico, aplica_financiero)
            VALUES
                (:id, 'Para Notificar', '#E3F2FD', '#1565C0', 2, true, true, true)
        """),
        {"id": now_ms},
    )

    # After the shift: "Legales para convenio" (id=1780942815469) is at orden=8,
    # "Administracion para NP" (id=1780942828789) is at orden=9.
    # The user's list wants them in the opposite order: Administracion para NP (8)
    # then Para Firma de Convenio (9).  Also rename "Legales para convenio".
    conn.execute(sa.text("UPDATE viv_cc_estados SET orden = 99 WHERE id = 1780942815469"))
    conn.execute(sa.text("UPDATE viv_cc_estados SET orden = 8  WHERE id = 1780942828789"))
    conn.execute(sa.text(
        "UPDATE viv_cc_estados SET label = 'Para Firma de Convenio', orden = 9 WHERE id = 1780942815469"
    ))

    # Recompute CC estado_general with the updated orden values
    conn.execute(sa.text("""
        WITH ranked AS (
            SELECT
                m.id AS mun_id,
                e.id AS estado_id,
                ROW_NUMBER() OVER (PARTITION BY m.id ORDER BY e.orden ASC) AS rn
            FROM viv_cordon_cuneta m
            JOIN viv_cc_estados e
                ON e.id = ANY(
                    ARRAY_REMOVE(ARRAY[m.ejuridico, m.etecnico, m.efinanciero], NULL)
                )
            WHERE m.deleted_at IS NULL
        )
        UPDATE viv_cordon_cuneta m
        SET estado_general = r.estado_id
        FROM ranked r
        WHERE m.id = r.mun_id
          AND r.rn = 1
    """))

    # ─── CH: Align to the same 15-state workflow ──────────────────────────────

    # Move "Convenio Firmado" (id=9) to a temp orden to avoid conflicts while
    # we insert new states at orden 8 and 9
    conn.execute(sa.text("UPDATE viv_ch_estados SET orden = 99 WHERE id = 9"))

    # Rename and reorder existing CH states to match the standard workflow
    ch_updates = [
        # (id, new_label, bg, text_color, new_orden)
        (2,  "Sin Exp de Gobierno",                             "#FFF3CD", "#856404", 1),
        (3,  "Para Notificar",                                  "#E3F2FD", "#1565C0", 2),
        (4,  "Notificado",                                      "#DBEAFE", "#1E40AF", 3),
        (5,  "A la espera de Documentacion",                    "#FFE5D0", "#8B3A00", 4),
        (6,  "En revision tecnica",                             "#C8E6C9", "#1B5E20", 5),
        (7,  "En Correccion",                                   "#EDE7F6", "#4527A0", 6),
        (8,  "Documentacion Completada",                        "#E0F2F1", "#00695C", 7),
        (10, "Legales para Proyecto de Dictamen y Resolucion",  "#E8EAF6", "#1A237E", 11),
        (11, "Legales del MCyM",                                "#ECEFF1", "#455A64", 12),
    ]
    for ch_id, label, bg, text_color, orden in ch_updates:
        conn.execute(
            sa.text("""
                UPDATE viv_ch_estados
                SET label = :label, bg = :bg, text_color = :text_color, orden = :orden
                WHERE id = :id
            """),
            {"id": ch_id, "label": label, "bg": bg, "text_color": text_color, "orden": orden},
        )

    # Set "Convenio Firmado" to its final position
    conn.execute(sa.text("UPDATE viv_ch_estados SET orden = 10 WHERE id = 9"))

    # Insert the 4 new CH states that have no equivalent in the old catalog
    new_ch_states = [
        (now_ms + 1, "Administracion para NP",  "#FCE4EC", "#880E4F", 8),
        (now_ms + 2, "Para Firma de Convenio",  "#D4EDDA", "#155724", 9),
        (now_ms + 3, "Administracion OC",        "#ECEFF1", "#455A64", 13),
        (now_ms + 4, "TC",                       "#ECEFF1", "#455A64", 14),
    ]
    for ch_id, label, bg, text_color, orden in new_ch_states:
        conn.execute(
            sa.text("""
                INSERT INTO viv_ch_estados
                    (id, label, bg, text_color, orden, aplica_juridico, aplica_tecnico, aplica_financiero)
                VALUES
                    (:id, :label, :bg, :text_color, :orden, true, true, true)
            """),
            {"id": ch_id, "label": label, "bg": bg, "text_color": text_color, "orden": orden},
        )

    # Recompute CH estado_general with the updated orden values
    conn.execute(sa.text("""
        WITH ranked AS (
            SELECT
                l.id AS loc_id,
                e.id AS estado_id,
                ROW_NUMBER() OVER (PARTITION BY l.id ORDER BY e.orden ASC) AS rn
            FROM viv_cordoba_hogar l
            JOIN viv_ch_estados e
                ON e.id = ANY(
                    ARRAY_REMOVE(ARRAY[l.ejuridico, l.etecnico, l.efinanciero], NULL)
                )
            WHERE l.deleted_at IS NULL
        )
        UPDATE viv_cordoba_hogar l
        SET estado_general = r.estado_id
        FROM ranked r
        WHERE l.id = r.loc_id
          AND r.rn = 1
    """))


def downgrade() -> None:
    pass  # irreversible data migration — restore from backup if needed
