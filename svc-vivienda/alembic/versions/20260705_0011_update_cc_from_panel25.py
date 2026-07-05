"""Update viv_cordon_cuneta from Panel Cordón Cuneta #25 (2026-07-05)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-05 00:00:00.000000
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

UPDATE_TS = datetime(2026, 7, 5, tzinfo=timezone.utc)


# ── Data extracted from Panel_Cordon_Cuneta (25).html ────────────────────────
# (expediente, municipio, departamento, monto, cc_ml, adoq_m2, ok_gob, doc_exp_text, ej_label, et_label, ef_label)
MUNICIPALITIES = [
    ("0423-080115/2026", "LOS REARTES",             "Calamuchita",                    100000000,   None,   None, "SI", "A la espera de Documentacion",                    "Sin Iniciar",                                 "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079932/2026", "EMBALSE",                  "Calamuchita",                    200000000,   None,   None, "SI", "En Correccion",                                   "Sin Iniciar",                                 "En Correccion",                               "Sin Iniciar"),
    ("0423-079111/2026", "GUANACO MUERTO",            "Cruz del Eje",                   50000000,   None,   None, "SI", "En Correccion",                                   "Sin Iniciar",                                 "En Correccion",                               "Sin Iniciar"),
    ("0423-079110/2026", "LA BATEA",                  "Cruz del Eje",                   50000000,   None,   None, "SI", "NO ADHIERE AL PROGRAMA",                          "Sin Iniciar",                                 "Sin Iniciar",                                 "Sin Iniciar"),
    ("0423-079115/2026", "LA HIGUERA",                "Cruz del Eje",                  100000000,   None,   None, "SI", "En Correccion",                                   "En Correccion",                               "En Correccion",                               "Sin Iniciar"),
    ("0423-079112/2026", "LAS PLAYAS",                "Cruz del Eje",                  200000000,   None,   3922, "SI", "En Correccion",                                   "Documentacion Completada",                    "En Correccion",                               "Sin Iniciar"),
    ("0423-079113/2026", "TUCLAME",                   "Cruz del Eje",                  200000000,   None,   None, "SI", "TC",                                              "TC",                                          "Documentacion Completada",                    "Administracion OC"),
    ("0423-079098/2026", "DEL CAMPILLO",              "General Roca",                  200000000,   None,   7440, "SI", "En Correccion",                                   "En revision tecnica",                         "En Correccion",                               "Documentacion Completada"),
    ("0423-079133/2026", "GENERAL ROCA",              "General Roca",                  240000000,   None,   None, "SI", "TC",                                              "TC",                                          "Documentacion Completada",                    "Administracion OC"),
    ("0423-079097/2026", "VILLA HUIDOBRO",            "General Roca",                  200000000,   1100,   None, "SI", "En Correccion",                                   "Documentacion Completada",                    "En Correccion",                               "Sin Iniciar"),
    ("0423-079096/2026", "VILLA SARMIENTO",           "General Roca",                  210000000,   1530,   1575, "SI", "En Correccion",                                   "En Correccion",                               "En Correccion",                               "Sin Iniciar"),
    ("0423-079095/2026", "VILLA VALERIA",             "General Roca",                  350000000,   None,   5000, "SI", "TC",                                              "TC",                                          "Documentacion Completada",                    "Administracion OC"),
    ("0423-080117/2026", "OLAETA",                    "Juárez Celman",                 180000000,   None,   None, "SI", "En Correccion",                                   "A la espera de Documentacion",                "En Correccion",                               "Sin Iniciar"),
    ("0423-080116/2026", "CHARRAS",                   "Juárez Celman",                 100000000,   None,   3960, "SI", "En revision tecnica",                             "En revision tecnica",                         "En revision tecnica",                         "Sin Iniciar"),
    ("0423-080121/2026", "EL ARAÑADO",                "Juárez Celman",                 200000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-080118/2026", "SANTA EUFEMIA",             "Juárez Celman",                 200000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079785/2026", "ARIAS",                     "Marcos Juárez",                 100000000,   None,    921, "SI", "En Correccion",                                   "En revision tecnica",                         "En Correccion",                               "Sin Iniciar"),
    ("0423-079782/2026", "CAMILO ALDAO",              "Marcos Juárez",                 100000000,   None,   None, "SI", "En Correccion",                                   "En Correccion",                               "Documentacion Completada",                    "Administracion para NP"),
    ("0423-079103/2026", "CAP. GRAL. B. O'HIGGINS",  "Marcos Juárez",                 200000000,   None,   None, "SI", "En Correccion",                                   "Documentacion Completada",                    "En Correccion",                               "Sin Iniciar"),
    ("0423-079101/2026", "CAVANAGH",                  "Marcos Juárez",                 300000000,   None,   None, "SI", "A la espera de Documentacion",                    "En Correccion",                               "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079102/2026", "COLONIA ITALIANA",          "Marcos Juárez",                  80000000,    889,   None, "SI", "Legales para  Proyecto de Dictamen y Resolucion", "Legales para  Proyecto de Dictamen y Resolucion", "Documentacion Completada",               "Administracion para NP"),
    ("0423-079784/2026", "COMUNA COLONIA BARGE",      "Marcos Juárez",                  50000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079100/2026", "CRUZ ALTA",                 "Marcos Juárez",                 100000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079783/2026", "GENERAL BALDISSERA",        "Marcos Juárez",                 100000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079781/2026", "SAIRA",                     "Marcos Juárez",                 150000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-080119/2026", "LABOULAYE",                 "Presidente Roque Sáenz Peña",   200000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079809/2026", "LA CESIRA",                 "Presidente Roque Sáenz Peña",      200000,   None,   3440, "SI", "TC",                                              "TC",                                          "Documentacion Completada",                    "Administracion OC"),
    ("0423-079114/2026", "ROSALES",                   "Presidente Roque Sáenz Peña",   100000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079116/2026", "SAN JOAQUIN",               "Presidente Roque Sáenz Peña",    30000000,    206,   None, "SI", "En Correccion",                                   "En revision tecnica",                         "En Correccion",                               "Sin Iniciar"),
    ("0423-079943/2026", "CALCHÍN",                   "Río Segundo",                    50000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079942/2026", "CAPILLA DEL CARMEN",        "Río Segundo",                   100000000,   None,   None, "SI", "En Correccion",                                   "En revision tecnica",                         "En Correccion",                               "Sin Iniciar"),
    ("0423-079944/2026", "MATORRALES",                "Río Segundo",                    80000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079948/2026", "POZO DEL MOLLE",            "Río Segundo",                   200000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-079119/2026", "LA PAZ",                    "San Javier",                    300000000,    930,   2795, "SI", "Legales para  Proyecto de Dictamen y Resolucion", "Legales para  Proyecto de Dictamen y Resolucion", "Documentacion Completada",               "Administracion para NP"),
    ("0423-079121/2026", "LA POBLACIÓN",              "San Javier",                     75000000,    440,    870, "SI", "En Correccion",                                   "Documentacion Completada",                    "En Correccion",                               "Administracion OC"),
    ("0423-079117/2026", "LOS HORNILLOS",             "San Javier",                    150000000,    913,    534, "SI", "TC",                                              "TC",                                          "Documentacion Completada",                    "Administracion OC"),
    ("0423-079120/2026", "LUYABA",                    "San Javier",                    150000000,    300,   2050, "SI", "TC",                                              "TC",                                          "Documentacion Completada",                    "Administracion OC"),
    ("0423-079118/2026", "SAN JAVIER Y YACANTO",      "San Javier",                    200000000,   None,   1823, "SI", "En Correccion",                                   "Documentacion Completada",                    "En Correccion",                               "Administracion OC"),
    ("0423-080122/2026", "EL FORTIN",                 "San Justo",                     300000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-080123/2026", "LAS VARAS",                 "San Justo",                     150000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-080124/2026", "SACANTA",                   "San Justo",                      70000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-080120/2026", "ALICIA",                    "San Justo",                     200000000,   None,   None, "SI", "En Correccion",                                   "A la espera de Documentacion",                "En Correccion",                               "Sin Iniciar"),
    ("0423-079946/2026", "LAS VARILLAS",              "San Justo",                     400000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("0423-080125/2026", "VILLA DEL PRADO",           "Santa María",                    50000000,   None,   None, "SI", "En Correccion",                                   "A la espera de Documentacion",                "En Correccion",                               "Sin Iniciar"),
    ("0423-079945/2026", "VILLA PARQUE SANTA ANA",    "Santa María",                   200000000,   None,   None, "SI", "A la espera de Documentacion",                    "A la espera de Documentacion",                "A la espera de Documentacion",                "Sin Iniciar"),
    ("GOBDIGI-0541650111-426", "LAS PERDICES",        "Tercero Arriba",                124126724,   None,   None, "NO", "Sin Iniciar",                                     "Sin Iniciar",                                 "Sin Iniciar",                                 "Sin Iniciar"),
]

# New rows (47–54): not yet in the DB
# (expediente, municipio, departamento, monto, cc_ml, adoq_m2, ok_gob, doc_exp_text, ej_label, et_label, ef_label, orden)
NEW_MUNICIPALITIES = [
    ("0423-080477/2026", "ETRURIA",               "General San Martín",   None,       None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 47),
    ("0423-080479/2026", "MANFREDI",              "Río Segundo",          50000000,   None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 48),
    ("0423-080478/2026", "LA LAGUNA",             "General San Martín",   150000000,  None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 49),
    ("0423-080480/2026", "CHAZON",                "General San Martín",   100000000,  None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 50),
    ("0423-080481/2026", "AUSONIA",               "General San Martín",   80000000,   None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 51),
    ("0423-080476/2026", "TIO PUJIO",             "General San Martín",   150000000,  None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 52),
    ("0423-080446/2026", "SAN ANTONIO DE LITIN",  "Unión",                80000000,   None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 53),
    ("0423-080196/2026", "CRUZ ALTA",             "Marcos Juárez",        400000000,  None, None, "SI", "Notificado", "Notificado", "Sin Iniciar", "Sin Iniciar", 54),
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


def _insert_historial_cc(conn, row_id, campo, old_estado_id, new_estado_id):
    if old_estado_id == new_estado_id:
        return
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
            "ea": old_estado_id,
            "en": new_estado_id,
            "ts": UPDATE_TS,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    tabla_estados = "viv_cc_estados"
    estados = _load_estados(conn, tabla_estados)

    # ── Update existing rows ──────────────────────────────────────────────────
    for (exp, municipio, depto, monto, cc_ml, adoq, ok_gob, doc_exp, ej_l, et_l, ef_l) in MUNICIPALITIES:
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

        new_ej = estados.get(_normalize(ej_l))
        new_et = estados.get(_normalize(et_l))
        new_ef = estados.get(_normalize(ef_l))
        new_eg = _compute_estado_general(conn, tabla_estados, new_ej, new_et, new_ef)

        _insert_historial_cc(conn, row_id, "ejuridico", old_ej, new_ej)
        _insert_historial_cc(conn, row_id, "etecnico",  old_et, new_et)
        _insert_historial_cc(conn, row_id, "efinanciero", old_ef, new_ef)

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
                "municipio": municipio,
                "depto": depto,
                "monto": monto,
                "cc_ml": cc_ml,
                "adoq": adoq,
                "ok_gob": ok_gob,
                "doc_exp": doc_exp,
                "ej": new_ej,
                "et": new_et,
                "ef": new_ef,
                "eg": new_eg,
                "ts": UPDATE_TS,
                "id": row_id,
            },
        )

    # ── Insert new rows (47–54) ───────────────────────────────────────────────
    for (exp, municipio, depto, monto, cc_ml, adoq, ok_gob, doc_exp, ej_l, et_l, ef_l, orden) in NEW_MUNICIPALITIES:
        new_ej = estados.get(_normalize(ej_l))
        new_et = estados.get(_normalize(et_l))
        new_ef = estados.get(_normalize(ef_l))
        new_eg = _compute_estado_general(conn, tabla_estados, new_ej, new_et, new_ef)

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
                "id": new_id,
                "orden": orden,
                "municipio": municipio,
                "depto": depto,
                "exp": exp,
                "monto": monto,
                "cc_ml": cc_ml,
                "adoq": adoq,
                "ok_gob": ok_gob,
                "doc_exp": doc_exp,
                "ej": new_ej,
                "et": new_et,
                "ef": new_ef,
                "eg": new_eg,
                "ts": UPDATE_TS,
            },
        )

        # Historial entry for initial state (only non-"Sin Iniciar" campos)
        sin_iniciar_id = estados.get("sin iniciar")
        for campo, estado_id in [("ejuridico", new_ej), ("etecnico", new_et), ("efinanciero", new_ef)]:
            if estado_id is not None and estado_id != sin_iniciar_id:
                conn.execute(
                    sa.text("""
                        INSERT INTO viv_cc_estado_historial
                            (id, municipio_id, campo, estado_anterior_id, estado_nuevo_id, created_at, created_by)
                        VALUES (:id, :mid, :campo, NULL, :en, :ts, 'panel-25-5/7')
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "mid": new_id,
                        "campo": campo,
                        "en": estado_id,
                        "ts": UPDATE_TS,
                    },
                )


def downgrade() -> None:
    pass  # data migration — restore from backup if needed
