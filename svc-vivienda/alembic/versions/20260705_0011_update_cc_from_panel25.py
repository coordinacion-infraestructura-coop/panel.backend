"""Update viv_cordon_cuneta from Panel Cordón Cuneta #25 (2026-07-05)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-05 00:00:00.000000

Strategy for historial entries:
- If a dimension state CHANGED (old != new): insert with estado_date (the 📅 date from the HTML badge).
- If a dimension state DID NOT CHANGE but has no existing historial entry for that campo:
  also insert with estado_date using the previous-by-orden state as estado_anterior.
  This covers municipalities whose states were set by migration 0008 without historial entries.
- Skip "Sin Iniciar" for the second case (default/starting state, not a meaningful transition).
"""

import re
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


# ── Data extracted from Panel_Cordon_Cuneta (25).html ────────────────────────
# Each tuple: (expediente, municipio, departamento, monto, cc_ml, adoq_m2,
#              ok_gob, doc_exp_text, ej_label, et_label, ef_label,
#              estado_date)  ← (year, month, day) from the 📅 badge
MUNICIPALITIES = [
    ("0423-080115/2026", "LOS REARTES",             "Calamuchita",                   100000000,  None,  None, "SI", "A la espera de Documentacion",                    "Sin Iniciar",                                    "A la espera de Documentacion",    "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079932/2026", "EMBALSE",                  "Calamuchita",                   200000000,  None,  None, "SI", "En Correccion",                                   "Sin Iniciar",                                    "En Correccion",                   "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079111/2026", "GUANACO MUERTO",            "Cruz del Eje",                   50000000,  None,  None, "SI", "En Correccion",                                   "Sin Iniciar",                                    "En Correccion",                   "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079110/2026", "LA BATEA",                  "Cruz del Eje",                   50000000,  None,  None, "SI", "NO ADHIERE AL PROGRAMA",                          "Sin Iniciar",                                    "Sin Iniciar",                     "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079115/2026", "LA HIGUERA",                "Cruz del Eje",                  100000000,  None,  None, "SI", "En Correccion",                                   "En Correccion",                                  "En Correccion",                   "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079112/2026", "LAS PLAYAS",                "Cruz del Eje",                  200000000,  None,  3922, "SI", "En Correccion",                                   "Documentacion Completada",                       "En Correccion",                   "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079113/2026", "TUCLAME",                   "Cruz del Eje",                  200000000,  None,  None, "SI", "TC",                                              "TC",                                             "Documentacion Completada",        "Administracion OC",          (2026,  7,  2)),
    ("0423-079098/2026", "DEL CAMPILLO",              "General Roca",                  200000000,  None,  7440, "SI", "En Correccion",                                   "En revision tecnica",                            "En Correccion",                   "Documentacion Completada",   (2026,  7,  3)),
    ("0423-079133/2026", "GENERAL ROCA",              "General Roca",                  240000000,  None,  None, "SI", "TC",                                              "TC",                                             "Documentacion Completada",        "Administracion OC",          (2026,  6, 22)),
    ("0423-079097/2026", "VILLA HUIDOBRO",            "General Roca",                  200000000,  1100,  None, "SI", "En Correccion",                                   "Documentacion Completada",                       "En Correccion",                   "Sin Iniciar",                (2026,  6, 29)),
    ("0423-079096/2026", "VILLA SARMIENTO",           "General Roca",                  210000000,  1530,  1575, "SI", "En Correccion",                                   "En Correccion",                                  "En Correccion",                   "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079095/2026", "VILLA VALERIA",             "General Roca",                  350000000,  None,  5000, "SI", "TC",                                              "TC",                                             "Documentacion Completada",        "Administracion OC",          (2026,  6, 22)),
    ("0423-080117/2026", "OLAETA",                    "Juárez Celman",                 180000000,  None,  None, "SI", "En Correccion",                                   "A la espera de Documentacion",                   "En Correccion",                   "Sin Iniciar",                (2026,  6, 19)),
    ("0423-080116/2026", "CHARRAS",                   "Juárez Celman",                 100000000,  None,  3960, "SI", "En revision tecnica",                             "En revision tecnica",                            "En revision tecnica",             "Sin Iniciar",                (2026,  7,  3)),
    ("0423-080121/2026", "EL ARAÑADO",                "Juárez Celman",                 200000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6,  5)),
    ("0423-080118/2026", "SANTA EUFEMIA",             "Juárez Celman",                 200000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6,  5)),
    ("0423-079785/2026", "ARIAS",                     "Marcos Juárez",                 100000000,  None,   921, "SI", "En Correccion",                                   "En revision tecnica",                            "En Correccion",                   "Sin Iniciar",                (2026,  6, 22)),
    ("0423-079782/2026", "CAMILO ALDAO",              "Marcos Juárez",                 100000000,  None,  None, "SI", "En Correccion",                                   "En Correccion",                                  "Documentacion Completada",        "Administracion para NP",     (2026,  7,  2)),
    ("0423-079103/2026", "CAP. GRAL. B. O'HIGGINS",  "Marcos Juárez",                 200000000,  None,  None, "SI", "En Correccion",                                   "Documentacion Completada",                       "En Correccion",                   "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079101/2026", "CAVANAGH",                  "Marcos Juárez",                 300000000,  None,  None, "SI", "A la espera de Documentacion",                    "En Correccion",                                  "A la espera de Documentacion",    "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079102/2026", "COLONIA ITALIANA",          "Marcos Juárez",                  80000000,   889,  None, "SI", "Legales para  Proyecto de Dictamen y Resolucion", "Legales para  Proyecto de Dictamen y Resolucion", "Documentacion Completada",        "Administracion para NP",     (2026,  7,  2)),
    ("0423-079784/2026", "COMUNA COLONIA BARGE",      "Marcos Juárez",                  50000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  5, 11)),
    ("0423-079100/2026", "CRUZ ALTA",                 "Marcos Juárez",                 100000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  4, 10)),
    ("0423-079783/2026", "GENERAL BALDISSERA",        "Marcos Juárez",                 100000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  7,  3)),
    ("0423-079781/2026", "SAIRA",                     "Marcos Juárez",                 150000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  7,  3)),
    ("0423-080119/2026", "LABOULAYE",                 "Presidente Roque Sáenz Peña",   200000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6,  5)),
    ("0423-079809/2026", "LA CESIRA",                 "Presidente Roque Sáenz Peña",      200000,  None,  3440, "SI", "TC",                                              "TC",                                             "Documentacion Completada",        "Administracion OC",          (2026,  6, 18)),
    ("0423-079114/2026", "ROSALES",                   "Presidente Roque Sáenz Peña",   100000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6, 24)),
    ("0423-079116/2026", "SAN JOAQUIN",               "Presidente Roque Sáenz Peña",    30000000,   206,  None, "SI", "En Correccion",                                   "En revision tecnica",                            "En Correccion",                   "Sin Iniciar",                (2026,  6, 19)),
    ("0423-079943/2026", "CALCHÍN",                   "Río Segundo",                    50000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6, 19)),
    ("0423-079942/2026", "CAPILLA DEL CARMEN",        "Río Segundo",                   100000000,  None,  None, "SI", "En Correccion",                                   "En revision tecnica",                            "En Correccion",                   "Sin Iniciar",                (2026,  6, 30)),
    ("0423-079944/2026", "MATORRALES",                "Río Segundo",                    80000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6, 22)),
    ("0423-079948/2026", "POZO DEL MOLLE",            "Río Segundo",                   200000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  7,  1)),
    ("0423-079119/2026", "LA PAZ",                    "San Javier",                    300000000,   930,  2795, "SI", "Legales para  Proyecto de Dictamen y Resolucion", "Legales para  Proyecto de Dictamen y Resolucion", "Documentacion Completada",        "Administracion para NP",     (2026,  7,  2)),
    ("0423-079121/2026", "LA POBLACIÓN",              "San Javier",                     75000000,   440,   870, "SI", "En Correccion",                                   "Documentacion Completada",                       "En Correccion",                   "Administracion OC",          (2026,  6, 26)),
    ("0423-079117/2026", "LOS HORNILLOS",             "San Javier",                    150000000,   913,   534, "SI", "TC",                                              "TC",                                             "Documentacion Completada",        "Administracion OC",          (2026,  6, 26)),
    ("0423-079120/2026", "LUYABA",                    "San Javier",                    150000000,   300,  2050, "SI", "TC",                                              "TC",                                             "Documentacion Completada",        "Administracion OC",          (2026,  6, 18)),
    ("0423-079118/2026", "SAN JAVIER Y YACANTO",      "San Javier",                    200000000,  None,  1823, "SI", "En Correccion",                                   "Documentacion Completada",                       "En Correccion",                   "Administracion OC",          (2026,  6, 29)),
    ("0423-080122/2026", "EL FORTIN",                 "San Justo",                     300000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6, 18)),
    ("0423-080123/2026", "LAS VARAS",                 "San Justo",                     150000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6, 24)),
    ("0423-080124/2026", "SACANTA",                   "San Justo",                      70000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  6, 24)),
    ("0423-080120/2026", "ALICIA",                    "San Justo",                     200000000,  None,  None, "SI", "En Correccion",                                   "A la espera de Documentacion",                   "En Correccion",                   "Sin Iniciar",                (2026,  6, 25)),
    ("0423-079946/2026", "LAS VARILLAS",              "San Justo",                     400000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  5, 26)),
    ("0423-080125/2026", "VILLA DEL PRADO",           "Santa María",                    50000000,  None,  None, "SI", "En Correccion",                                   "A la espera de Documentacion",                   "En Correccion",                   "Sin Iniciar",                (2026,  6, 19)),
    ("0423-079945/2026", "VILLA PARQUE SANTA ANA",    "Santa María",                   200000000,  None,  None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                   "A la espera de Documentacion",    "Sin Iniciar",                (2026,  5, 26)),
    ("GOBDIGI-0541650111-426", "LAS PERDICES",        "Tercero Arriba",                124126724,  None,  None, "NO", "Sin Iniciar",                                     "Sin Iniciar",                                    "Sin Iniciar",                     "Sin Iniciar",                (2026,  4, 27)),
]

# New rows (47–54): not yet in the DB
# (expediente, municipio, departamento, monto, cc_ml, adoq_m2,
#  ok_gob, doc_exp_text, ej_label, et_label, ef_label, orden, estado_date)
NEW_MUNICIPALITIES = [
    ("0423-080477/2026", "ETRURIA",               "General San Martín",  None,      None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 47, (2026, 7, 3)),
    ("0423-080479/2026", "MANFREDI",              "Río Segundo",         50000000,  None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 48, (2026, 7, 3)),
    ("0423-080478/2026", "LA LAGUNA",             "General San Martín",  150000000, None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 49, (2026, 7, 3)),
    ("0423-080480/2026", "CHAZON",                "General San Martín",  100000000, None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 50, (2026, 7, 3)),
    ("0423-080481/2026", "AUSONIA",               "General San Martín",  80000000,  None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 51, (2026, 7, 3)),
    ("0423-080476/2026", "TIO PUJIO",             "General San Martín",  150000000, None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 52, (2026, 7, 3)),
    ("0423-080446/2026", "SAN ANTONIO DE LITIN",  "Unión",               80000000,  None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 53, (2026, 7, 3)),
    ("0423-080196/2026", "CRUZ ALTA",             "Marcos Juárez",       400000000, None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 54, (2026, 7, 3)),
]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _load_estados(conn, tabla: str) -> dict:
    rows = conn.execute(sa.text(f"SELECT id, label FROM {tabla}")).fetchall()
    return {_normalize(label): row_id for row_id, label in rows}


def _compute_estado_general(conn, tabla: str, ej, et, ef):
    ids = [x for x in [ej, et, ef] if x is not None]
    if not ids:
        return None
    placeholders = ", ".join(f":i{n}" for n in range(len(ids)))
    params = {f"i{n}": v for n, v in enumerate(ids)}
    row = conn.execute(
        sa.text(f"SELECT id FROM {tabla} WHERE id IN ({placeholders}) ORDER BY orden ASC LIMIT 1"),
        params,
    ).fetchone()
    return row[0] if row else None


def _prev_estado(conn, tabla: str, estado_id) -> int | None:
    """Estado with the immediately lower orden (the 'before' state)."""
    row = conn.execute(
        sa.text(f"""
            SELECT id FROM {tabla}
            WHERE orden < (SELECT orden FROM {tabla} WHERE id = :id)
            ORDER BY orden DESC LIMIT 1
        """),
        {"id": estado_id},
    ).fetchone()
    return row[0] if row else None


def _insert_historial(conn, row_id, campo, anterior_id, nuevo_id, ts):
    conn.execute(
        sa.text("""
            INSERT INTO viv_cc_estado_historial
                (id, municipio_id, campo, estado_anterior_id, estado_nuevo_id, created_at, created_by)
            VALUES (:id, :mid, :campo, :ea, :en, :ts, 'panel-25-5/7')
        """),
        {
            "id": str(uuid.uuid4()),
            "mid": row_id,
            "campo": campo,
            "ea": anterior_id,
            "en": nuevo_id,
            "ts": ts,
        },
    )


def _ensure_historial(conn, tabla_estados: str, row_id, campo, nuevo_id, ts):
    """Insert historial entry if no entry already exists for this campo+estado."""
    existing = conn.execute(
        sa.text("""
            SELECT 1 FROM viv_cc_estado_historial
            WHERE municipio_id = :mid AND campo = :campo AND estado_nuevo_id = :en
            LIMIT 1
        """),
        {"mid": row_id, "campo": campo, "en": nuevo_id},
    ).fetchone()
    if existing:
        return
    anterior_id = _prev_estado(conn, tabla_estados, nuevo_id)
    _insert_historial(conn, row_id, campo, anterior_id, nuevo_id, ts)


def upgrade() -> None:
    conn = op.get_bind()
    tabla_estados = "viv_cc_estados"
    estados = _load_estados(conn, tabla_estados)
    sin_iniciar_id = estados.get("sin iniciar")

    # ── Update existing rows ──────────────────────────────────────────────────
    for row_data in MUNICIPALITIES:
        exp, municipio, depto, monto, cc_ml, adoq, ok_gob, doc_exp, ej_l, et_l, ef_l, estado_ymd = row_data

        row = conn.execute(
            sa.text("""
                SELECT id, ejuridico, etecnico, efinanciero
                FROM viv_cordon_cuneta
                WHERE expediente = :e AND deleted_at IS NULL
            """),
            {"e": exp},
        ).fetchone()
        if not row:
            continue

        row_id, old_ej, old_et, old_ef = row
        ts = datetime(*estado_ymd, tzinfo=timezone.utc)

        new_ej = estados.get(_normalize(ej_l))
        new_et = estados.get(_normalize(et_l))
        new_ef = estados.get(_normalize(ef_l))
        new_eg = _compute_estado_general(conn, tabla_estados, new_ej, new_et, new_ef)

        # Historial: changed campos use old→new with the HTML badge date;
        # unchanged non-Sin-Iniciar campos get an entry if none exists yet.
        for campo, old_id, new_id in [
            ("ejuridico",   old_ej, new_ej),
            ("etecnico",    old_et, new_et),
            ("efinanciero", old_ef, new_ef),
        ]:
            if new_id is None:
                continue
            if old_id != new_id:
                _insert_historial(conn, row_id, campo, old_id, new_id, ts)
            elif new_id != sin_iniciar_id:
                _ensure_historial(conn, tabla_estados, row_id, campo, new_id, ts)

        conn.execute(
            sa.text("""
                UPDATE viv_cordon_cuneta SET
                    municipio         = :municipio,
                    departamento      = :depto,
                    monto             = :monto,
                    cordon_cuneta_ml  = :cc_ml,
                    adoquinado_m2     = :adoq,
                    ok_gob            = :ok_gob,
                    doc_exp           = :doc_exp,
                    ejuridico         = :ej,
                    etecnico          = :et,
                    efinanciero       = :ef,
                    estado_general    = :eg,
                    updated_at        = :ts,
                    updated_by        = 'panel-25-5/7'
                WHERE id = :id
            """),
            {
                "municipio": municipio, "depto": depto, "monto": monto,
                "cc_ml": cc_ml, "adoq": adoq, "ok_gob": ok_gob,
                "doc_exp": doc_exp, "ej": new_ej, "et": new_et,
                "ef": new_ef, "eg": new_eg, "ts": ts, "id": row_id,
            },
        )

    # ── Insert new rows (47–54) ───────────────────────────────────────────────
    for row_data in NEW_MUNICIPALITIES:
        exp, municipio, depto, monto, cc_ml, adoq, ok_gob, doc_exp, ej_l, et_l, ef_l, orden, estado_ymd = row_data

        new_ej = estados.get(_normalize(ej_l))
        new_et = estados.get(_normalize(et_l))
        new_ef = estados.get(_normalize(ef_l))
        new_eg = _compute_estado_general(conn, tabla_estados, new_ej, new_et, new_ef)
        ts = datetime(*estado_ymd, tzinfo=timezone.utc)

        new_id = str(uuid.uuid4())
        conn.execute(
            sa.text("""
                INSERT INTO viv_cordon_cuneta
                    (id, orden, municipio, departamento, expediente, monto,
                     cordon_cuneta_ml, adoquinado_m2, ok_gob, doc_exp,
                     ejuridico, etecnico, efinanciero, estado_general,
                     created_at, updated_at, updated_by)
                VALUES
                    (:id, :orden, :municipio, :depto, :exp, :monto,
                     :cc_ml, :adoq, :ok_gob, :doc_exp,
                     :ej, :et, :ef, :eg,
                     :ts, :ts, 'panel-25-5/7')
            """),
            {
                "id": new_id, "orden": orden, "municipio": municipio,
                "depto": depto, "exp": exp, "monto": monto,
                "cc_ml": cc_ml, "adoq": adoq, "ok_gob": ok_gob,
                "doc_exp": doc_exp, "ej": new_ej, "et": new_et,
                "ef": new_ef, "eg": new_eg, "ts": ts,
            },
        )

        # Historial for initial state (only non-Sin-Iniciar campos)
        for campo, estado_id in [("ejuridico", new_ej), ("etecnico", new_et), ("efinanciero", new_ef)]:
            if estado_id is not None and estado_id != sin_iniciar_id:
                anterior_id = _prev_estado(conn, tabla_estados, estado_id)
                _insert_historial(conn, new_id, campo, anterior_id, estado_id, ts)


def downgrade() -> None:
    pass  # data migration — restore from backup if needed
