"""Backfill CC estado historial entries from Panel #25

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-05 00:00:00.000001

Migration 0011 updated all estado columns correctly but did not insert
historial entries for municipalities whose dimension states did not change
between Panel 15 and Panel 25 (the _ensure_historial branch was absent in
the version that ran on Cloud Shell).

This migration inserts the missing entries using the per-municipality badge
dates from Panel 25. It skips any campo that already has an entry with the
same estado_nuevo_id (idempotent).
"""

import re
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


# (expediente, ej_label, et_label, ef_label, estado_ymd)
# LAS PERDICES (all Sin Iniciar) and LA BATEA ("NO ADHIERE") are omitted.
PANEL25 = [
    # ── Calamuchita ──────────────────────────────────────────────────────────
    ("0423-080115/2026", "Sin Iniciar",                                    "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 7,  3)),  # LOS REARTES
    ("0423-079932/2026", "Sin Iniciar",                                    "En Correccion",                                   "Sin Iniciar",             (2026, 7,  3)),  # EMBALSE
    # ── Cruz del Eje ─────────────────────────────────────────────────────────
    ("0423-079111/2026", "Sin Iniciar",                                    "En Correccion",                                   "Sin Iniciar",             (2026, 7,  3)),  # GUANACO MUERTO
    ("0423-079115/2026", "En Correccion",                                  "En Correccion",                                   "Sin Iniciar",             (2026, 7,  3)),  # LA HIGUERA
    ("0423-079112/2026", "Documentacion Completada",                       "En Correccion",                                   "Sin Iniciar",             (2026, 7,  3)),  # LAS PLAYAS
    ("0423-079113/2026", "TC",                                             "Documentacion Completada",                        "Administracion OC",       (2026, 7,  2)),  # TUCLAME
    # ── General Roca ─────────────────────────────────────────────────────────
    ("0423-079098/2026", "En revision tecnica",                            "En Correccion",                                   "Documentacion Completada",(2026, 7,  3)),  # DEL CAMPILLO
    ("0423-079133/2026", "TC",                                             "Documentacion Completada",                        "Administracion OC",       (2026, 6, 22)),  # GENERAL ROCA
    ("0423-079097/2026", "Documentacion Completada",                       "En Correccion",                                   "Sin Iniciar",             (2026, 6, 29)),  # VILLA HUIDOBRO
    ("0423-079096/2026", "En Correccion",                                  "En Correccion",                                   "Sin Iniciar",             (2026, 7,  3)),  # VILLA SARMIENTO
    ("0423-079095/2026", "TC",                                             "Documentacion Completada",                        "Administracion OC",       (2026, 6, 22)),  # VILLA VALERIA
    # ── Juárez Celman ────────────────────────────────────────────────────────
    ("0423-080117/2026", "A la espera de Documentacion",                   "En Correccion",                                   "Sin Iniciar",             (2026, 6, 19)),  # OLAETA
    ("0423-080116/2026", "En revision tecnica",                            "En revision tecnica",                             "Sin Iniciar",             (2026, 7,  3)),  # CHARRAS
    ("0423-080121/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6,  5)),  # EL ARAÑADO
    ("0423-080118/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6,  5)),  # SANTA EUFEMIA
    # ── Marcos Juárez ────────────────────────────────────────────────────────
    ("0423-079785/2026", "En revision tecnica",                            "En Correccion",                                   "Sin Iniciar",             (2026, 6, 22)),  # ARIAS
    ("0423-079782/2026", "En Correccion",                                  "Documentacion Completada",                        "Administracion para NP",  (2026, 7,  2)),  # CAMILO ALDAO
    ("0423-079103/2026", "Documentacion Completada",                       "En Correccion",                                   "Sin Iniciar",             (2026, 7,  3)),  # CAP. GRAL. B. O'HIGGINS
    ("0423-079101/2026", "En Correccion",                                  "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 7,  3)),  # CAVANAGH
    ("0423-079102/2026", "Legales para  Proyecto de Dictamen y Resolucion","Documentacion Completada",                        "Administracion para NP",  (2026, 7,  2)),  # COLONIA ITALIANA
    ("0423-079784/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 5, 11)),  # COLONIA BARGE
    ("0423-079100/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 4, 10)),  # CRUZ ALTA
    ("0423-079783/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 7,  3)),  # GENERAL BALDISSERA
    ("0423-079781/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 7,  3)),  # SAIRA
    # ── Presidente Roque Sáenz Peña ─────────────────────────────────────────
    ("0423-080119/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6,  5)),  # LABOULAYE
    ("0423-079809/2026", "TC",                                             "Documentacion Completada",                        "Administracion OC",       (2026, 6, 18)),  # LA CESIRA
    ("0423-079114/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6, 24)),  # ROSALES
    ("0423-079116/2026", "En revision tecnica",                            "En Correccion",                                   "Sin Iniciar",             (2026, 6, 19)),  # SAN JOAQUIN
    # ── Río Segundo ──────────────────────────────────────────────────────────
    ("0423-079943/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6, 19)),  # CALCHÍN
    ("0423-079942/2026", "En revision tecnica",                            "En Correccion",                                   "Sin Iniciar",             (2026, 6, 30)),  # CAPILLA DEL CARMEN
    ("0423-079944/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6, 22)),  # MATORRALES
    ("0423-079948/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 7,  1)),  # POZO DEL MOLLE
    # ── San Javier ───────────────────────────────────────────────────────────
    ("0423-079119/2026", "Legales para  Proyecto de Dictamen y Resolucion","Documentacion Completada",                        "Administracion para NP",  (2026, 7,  2)),  # LA PAZ
    ("0423-079121/2026", "Documentacion Completada",                       "En Correccion",                                   "Administracion OC",       (2026, 6, 26)),  # LA POBLACIÓN
    ("0423-079117/2026", "TC",                                             "Documentacion Completada",                        "Administracion OC",       (2026, 6, 26)),  # LOS HORNILLOS
    ("0423-079120/2026", "TC",                                             "Documentacion Completada",                        "Administracion OC",       (2026, 6, 18)),  # LUYABA
    ("0423-079118/2026", "Documentacion Completada",                       "En Correccion",                                   "Administracion OC",       (2026, 6, 29)),  # SAN JAVIER Y YACANTO
    # ── San Justo ────────────────────────────────────────────────────────────
    ("0423-080122/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6, 18)),  # EL FORTIN
    ("0423-080123/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6, 24)),  # LAS VARAS
    ("0423-080124/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 6, 24)),  # SACANTA
    ("0423-080120/2026", "A la espera de Documentacion",                   "En Correccion",                                   "Sin Iniciar",             (2026, 6, 25)),  # ALICIA
    ("0423-079946/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 5, 26)),  # LAS VARILLAS
    # ── Santa María ──────────────────────────────────────────────────────────
    ("0423-080125/2026", "A la espera de Documentacion",                   "En Correccion",                                   "Sin Iniciar",             (2026, 6, 19)),  # VILLA DEL PRADO
    ("0423-079945/2026", "A la espera de Documentacion",                   "A la espera de Documentacion",                    "Sin Iniciar",             (2026, 5, 26)),  # VILLA PARQUE SANTA ANA
    # ── 8 new rows inserted by migration 0011 (Notificado) ───────────────────
    ("0423-080477/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # ETRURIA
    ("0423-080479/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # MANFREDI
    ("0423-080478/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # LA LAGUNA
    ("0423-080480/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # CHAZON
    ("0423-080481/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # AUSONIA
    ("0423-080476/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # TIO PUJIO
    ("0423-080446/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # SAN ANTONIO DE LITIN
    ("0423-080196/2026", "Notificado", "Sin Iniciar", "Sin Iniciar", (2026, 7, 3)),  # CRUZ ALTA (new)
]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _load_estados(conn, tabla: str) -> dict:
    rows = conn.execute(sa.text(f"SELECT id, label FROM {tabla}")).fetchall()
    return {_normalize(label): row_id for row_id, label in rows}


def _prev_estado(conn, tabla: str, estado_id):
    row = conn.execute(
        sa.text(f"""
            SELECT id FROM {tabla}
            WHERE orden < (SELECT orden FROM {tabla} WHERE id = :id)
            ORDER BY orden DESC LIMIT 1
        """),
        {"id": estado_id},
    ).fetchone()
    return row[0] if row else None


def _insert_historial(conn, municipio_id, campo, anterior_id, nuevo_id, ts):
    conn.execute(
        sa.text("""
            INSERT INTO viv_cc_estado_historial
                (id, municipio_id, campo, estado_anterior_id, estado_nuevo_id, created_at, created_by)
            VALUES (:id, :mid, :campo, :ea, :en, :ts, 'panel-25-backfill')
        """),
        {
            "id": str(uuid.uuid4()),
            "mid": municipio_id,
            "campo": campo,
            "ea": anterior_id,
            "en": nuevo_id,
            "ts": ts,
        },
    )


def _ensure(conn, tabla_estados: str, municipio_id, campo, estado_id, ts):
    """Insert historial entry if none already exists for (municipio, campo, estado_nuevo)."""
    existing = conn.execute(
        sa.text("""
            SELECT 1 FROM viv_cc_estado_historial
            WHERE municipio_id = :mid AND campo = :campo AND estado_nuevo_id = :en
            LIMIT 1
        """),
        {"mid": municipio_id, "campo": campo, "en": estado_id},
    ).fetchone()
    if existing:
        return
    anterior_id = _prev_estado(conn, tabla_estados, estado_id)
    _insert_historial(conn, municipio_id, campo, anterior_id, estado_id, ts)


def upgrade() -> None:
    conn = op.get_bind()
    tabla_estados = "viv_cc_estados"
    estados = _load_estados(conn, tabla_estados)
    sin_iniciar_id = estados.get("sin iniciar")

    for exp, ej_l, et_l, ef_l, estado_ymd in PANEL25:
        row = conn.execute(
            sa.text("""
                SELECT id FROM viv_cordon_cuneta
                WHERE expediente = :e AND deleted_at IS NULL
            """),
            {"e": exp},
        ).fetchone()
        if not row:
            continue

        municipio_id = row[0]
        ts = datetime(*estado_ymd, tzinfo=timezone.utc)

        for campo, label in [("ejuridico", ej_l), ("etecnico", et_l), ("efinanciero", ef_l)]:
            estado_id = estados.get(_normalize(label))
            if estado_id is None or estado_id == sin_iniciar_id:
                continue
            _ensure(conn, tabla_estados, municipio_id, campo, estado_id, ts)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM viv_cc_estado_historial WHERE created_by = 'panel-25-backfill'")
    )
