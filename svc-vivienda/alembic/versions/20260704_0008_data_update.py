"""Actualización datos: CC estados renovados, 54 municipios CC, CH updates, geo seed

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-04 00:00:00.000000
"""
import json
import os
import uuid as _uuid
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# CC estados renovados (mismo esquema de IDs que el HTML Panel 15)
# Los IDs timestamp se mantienen pero los labels/colores/orden cambian
# ---------------------------------------------------------------------------
CC_ESTADOS_UPDATE = [
    # id, label, bg, text_color, orden
    (1,              "Sin Iniciar",                                        "#ECEFF1", "#455A64",  0),
    (2,              "Sin Exp de Gobierno",                                "#FFF3CD", "#856404",  1),
    (3,              "Para Notificar",                                     "#DBEAFE", "#1E40AF",  2),
    (4,              "Notificado",                                         "#FFE5D0", "#8B3A00",  3),
    (1780930869659,  "A la espera de Documentacion",                       "#C8E6C9", "#1B5E20",  4),
    (1780942780772,  "En revision tecnica",                                "#EDE7F6", "#4527A0",  5),
    (1780942808606,  "En Correccion",                                      "#E0F2F1", "#00695C",  6),
    (1780942828789,  "Documentacion Completada",                           "#FCE4EC", "#880E4F",  7),
    (1780942838431,  "Administracion para NP",                             "#E0F7FA", "#006064",  8),
    (1780942843788,  "Para Firma de Convenio",                             "#E8EAF6", "#1A237E",  9),
    (1781710357683,  "Convenio Firmado",                                   "#FFF8E1", "#F57F17", 10),
    (1781710640727,  "Legales para Proyecto de Dictamen y Resolucion",     "#D7CCC8", "#4E342E", 11),
    (1781737487934,  "Legales del MCyM",                                   "#FFCDD2", "#B71C1C", 12),
]
CC_ESTADOS_NEW = [
    (1783045296250, "Administracion OC", "#ECEFF1", "#455A64", 13),
    (1783045450704, "TC",                "#ECEFF1", "#455A64", 14),
]

# ---------------------------------------------------------------------------
# CC municipios — 46 existentes (identificados por expediente), 8 nuevos
# ejuridico/etecnico/efinanciero ya usan los nuevos IDs del HTML
# ---------------------------------------------------------------------------
CC_MUNICIPIOS_UPDATE = [
    # (expediente, municipio, departamento, monto, cc_ml, adq_m2, ok_gob, doc_exp, ejuridico, etecnico, efinanciero, obs)
    ("0423-080115/2026", "LOS REARTES",           "Calamuchita",                None,  None, "SI", "A la espera de Documentacion",          1,             1780930869659, 1,             "22/6 ultma comunicacion\n2/7 me comunico yo"),
    ("0423-079932/2026", "EMBALSE",                "Calamuchita",                None,  None, "SI", "En Correccion",                         1,             1780942808606, 1,             "1/7 se mandan correcciones, nuevamente"),
    ("0423-079111/2026", "GUANACO MUERTO",         "Cruz del Eje",               None,  None, "SI", "En Correccion",                         1,             1780942808606, 1,             "18/6 ultima comunicacion\n1/7 me comunico con el Pte"),
    ("0423-079110/2026", "LA BATEA",               "Cruz del Eje",               None,  None, "SI", "NO ADHIERE AL PROGRAMA",                1,             1,             1,             ""),
    ("0423-079115/2026", "LA HIGUERA",             "Cruz del Eje",               None,  None, "SI", "En Correccion",                         1780942808606, 1780942808606, 1,             "30/6 se vuelve a solicitar la correccion de la doc"),
    ("0423-079112/2026", "LAS PLAYAS",             "Cruz del Eje",               None,  3922, "SI", "En Correccion",                         1780942828789, 1780942808606, 1,             "26 y 29/6 se envian correcciones"),
    ("0423-079113/2026", "TUCLAME",                "Cruz del Eje",               None,  None, "SI", "TC",                                    1783045450704, 1780942828789, 1783045296250, "Se solicito geolocalizacion a la Muni (pedido del TC)"),
    ("0423-079098/2026", "DEL CAMPILLO",           "General Roca",               None,  7440, "SI", "En Correccion",                         1780942780772, 1780942808606, 1780942828789, ""),
    ("0423-079133/2026", "GENERAL ROCA",           "General Roca",               None,  None, "SI", "TC",                                    1783045450704, 1780942828789, 1783045296250, ""),
    ("0423-079097/2026", "VILLA HUIDOBRO",         "General Roca",               1100, None,  "SI", "En Correccion",                         1780942828789, 1780942808606, 1,             "30/6 nos volvemos a comunicar"),
    ("0423-079096/2026", "VILLA SARMIENTO",        "General Roca",               1530, 1575,  "SI", "Documentacion Completada",              1780942828789, 1780942828789, 1,             "GOBDIGI-0526923111-226"),
    ("0423-079095/2026", "VILLA VALERIA",          "General Roca",               None,  None, "SI", "22/6 TC",                               1781737487934, 1780942808606, 1781737487934, "Antes de ARCHIVAR el exp 0135-044666/2026, dejar SIN EFECTO la RESO"),
    ("0423-080117/2026", "OLAETA",                 "Juárez Celman",              None,  None, "SI", "4/6 se NOTIFICA a la Municipalidad",    3,             4,             1,             ""),
    ("0423-080116/2026", "CHARRAS",                "Juárez Celman",              None,  None, "SI", "PARA FIRMAR CONVENIO",                  3,             1780942780772, 1,             ""),
    ("0423-080121/2026", "EL ARAÑADO",             "Juárez Celman",              None,  None, "SI", "4/6 se NOTIFICA a la Municipalidad",    3,             4,             1,             ""),
    ("0423-080118/2026", "SANTA EUFEMIA",          "Juárez Celman",              None,  None, "SI", "4/6 se NOTIFICA a la Municipalidad",    3,             4,             1,             ""),
    ("0423-079785/2026", "ARIAS",                  "Marcos Juárez",              None,  921,  "SI", "8/5 se NOTIFICA a la Municipalidad",    3,             1780930869659, 1,             ""),
    ("0423-079782/2026", "CAMILO ALDAO",           "Marcos Juárez",              None,  None, "SI", "8/5 se NOTIFICA a la Municipalidad",    1780942843788, 1780942808606, 1780942828789, "30/6 PARA NP"),
    ("0423-079103/2026", "CAP. GRAL. B. O'HIGGINS","Marcos Juárez",              None,  None, "SI", "10/4 se NOTIFICA a la Municipalidad",   3,             4,             1,             ""),
    ("0423-079101/2026", "CAVANAGH",               "Marcos Juárez",              None,  None, "SI", "PARA FIRMAR CONVENIO",                  3,             1780942780772, 1,             ""),
    ("0423-079102/2026", "COLONIA ITALIANA",       "Marcos Juárez",              889,   None, "SI", "19/6 Se FIRMA CONVENIO",                1780942843788, 1780942808606, 1780942828789, "30/6 PARA NP"),
    ("0423-079784/2026", "COMUNA COLONIA BARGE",   "Marcos Juárez",              None,  None, "SI", "8/5 se NOTIFICA a la Municipalidad",    3,             4,             1,             ""),
    ("0423-079100/2026", "CRUZ ALTA",              "Marcos Juárez",              None,  None, "SI", "10/4 se NOTIFICA a la Municipalidad",   3,             4,             1,             ""),
    ("0423-079783/2026", "GENERAL BALDISSERA",     "Marcos Juárez",              None,  None, "SI", "8/5 se NOTIFICA  a la Municipalidad",   3,             4,             1,             ""),
    ("0423-079781/2026", "SAIRA",                  "Marcos Juárez",              None,  None, "SI", "8/5 se NOTIFICA a la Municipalidad",    3,             4,             1,             ""),
    ("0423-080119/2026", "LABOULAYE",              "Presidente Roque Sáenz Peña",None,  None, "SI", "4/6 se NOTIFICA a la Municipalidad",    3,             4,             1,             ""),
    ("0423-079809/2026", "LA CESIRA",              "Presidente Roque Sáenz Peña",None,  3440, "SI", "TC 17/6",                               1781737487934, 1780942808606, 1781737487934, "0135-044777/2026 dejar SIN EFECTO LA RESO"),
    ("0423-079114/2026", "ROSALES",                "Presidente Roque Sáenz Peña",None,  None, "SI", "10/4 se NOTIFICA a la Municipalidad",   3,             1,             1,             ""),
    ("0423-079116/2026", "SAN JOAQUIN",            "Presidente Roque Sáenz Peña",206,   None, "SI", "19/6 Se FIRMA CONVENIO",                1780930869659, 1780942780772, 1,             ""),
    ("0423-079943/2026", "CALCHÍN",                "Río Segundo",                None,  None, "SI", "26/5 se NOTIFICA a la Municipalidad",   3,             4,             1,             ""),
    ("0423-079942/2026", "CAPILLA DEL CARMEN",     "Río Segundo",                None,  None, "SI", "26/5 se NOTIFICA  a la Municipalidad",  3,             4,             1,             ""),
    ("0423-079944/2026", "MATORRALES",             "Río Segundo",                None,  None, "SI", "26/5 se NOTIFICA a la Municipalidad",   3,             4,             1,             ""),
    ("0423-079948/2026", "POZO DEL MOLLE",         "Río Segundo",                None,  None, "SI", "26/5 se NOTIFICA a la Municipalidad",   3,             4,             1,             ""),
    ("0423-079119/2026", "LA PAZ",                 "San Javier",                 930,   2795, "SI", "19/6 se FIRMA CONVENIO",                1780942843788, 1780942808606, 1780942828789, "30/6 PARA NP"),
    ("0423-079121/2026", "LA POBLACIÓN",           "San Javier",                 440,   870,  "SI", "Vuelve el 26/6 para GEOLOCALIZACION - 17/6 TC", 4, 1780942808606, 1781737487934, ""),
    ("0423-079117/2026", "LOS HORNILLOS",          "San Javier",                 913,   534,  "SI", "17/6 TC",                               1781737487934, 1780942808606, 1781737487934, ""),
    ("0423-079120/2026", "LUYABA",                 "San Javier",                 300,   2050, "SI", "17/6 TC",                               1781737487934, 1780942808606, 1781737487934, ""),
    ("0423-079118/2026", "SAN JAVIER Y YACANTO",   "San Javier",                 None,  1823, "SI", "29/6 vuelve para GEOLOCALIZACION - 18/6 TC", 4, 1780942808606, 1,        ""),
    ("0423-080122/2026", "EL FORTIN",              "San Justo",                  None,  None, "SI", "4/6 se NOTIFCA a la Municipalidad",     3,             4,             1,             ""),
    ("0423-080123/2026", "LAS VARAS",              "San Justo",                  None,  None, "SI", "4/6 se NOTIFICA a la Municipalidad",    3,             1,             1,             ""),
    ("0423-080124/2026", "SACANTA",                "San Justo",                  None,  None, "SI", "4/6 se NOTIFICA a la Municipalidad",    3,             1,             1,             ""),
    ("0423-080120/2026", "ALICIA",                 "San Justo",                  None,  None, "SI", "se NOTIFICA a la Municipalidad",         1,             1,             1,             ""),
    ("0423-079946/2026", "LAS VARILLAS",           "San Justo",                  None,  None, "SI", "26/5 se NOTIFICA a la Municipalidad",   3,             4,             1,             ""),
    ("0423-080125/2026", "VILLA DEL PRADO",        "Santa María",                None,  None, "SI", "4/6 se NOTIFICA a la Municipalidad",    3,             1,             1,             ""),
    ("0423-079945/2026", "VILLA PARQUE SANTA ANA", "Santa María",                None,  None, "SI", "26/5 se NOTIFICA a la Municipalidad",   3,             4,             1,             ""),
    ("GOBDIGI-0541650111-426", "LAS PERDICES",     "Tercero Arriba",             None,  None, "NO", "27/4 Privada de VIVIENDA",              1,             1,             1,             ""),
]
# cc_ml and adq_m2 are at index 3 and 4 of tuple above

CC_MUNICIPIOS_NEW = [
    # orden, municipio, departamento, expediente, monto, cc_ml, adq_m2, ok_gob, doc_exp, ejuridico, etecnico, efinanciero, obs
    (47, "ETRURIA",            "General San Martín", "0423-080477/2026", 0,         None, None, "SI", "Para Notificar", 3, 1, 1, ""),
    (48, "MANFREDI",           "Río Segundo",        "0423-080479/2026", 50000000,  None, None, "SI", "Para Notificar", 3, 1, 1, ""),
    (49, "LA LAGUNA",          "General San Martín", "0423-080478/2026", 150000000, None, None, "SI", "Para Notificar", 3, 1, 1, ""),
    (50, "CHAZON",             "General San Martín", "0423-080480/2026", 100000000, None, None, "SI", "Para Notificar", 3, 1, 1, ""),
    (51, "AUSONIA",            "General San Martín", "0423-080481/2026", 80000000,  None, None, "SI", "Para Notificar", 3, 1, 1, ""),
    (52, "TIO PUJIO",          "General San Martín", "0423-080476/2026", 150000000, None, None, "SI", "Para Notificar", 3, 1, 1, ""),
    (53, "SAN ANTONIO DE LITIN","Unión",             "0423-080446/2026", 80000000,  None, None, "SI", "Para Notificar", 3, 1, 1, ""),
    (54, "CRUZ ALTA",          "Marcos Juárez",      "0423-080196/2026", 400000000, None, None, "SI", "Para Notificar", 3, 1, 1, ""),
]


def upgrade() -> None:
    conn = op.get_bind()

    # -----------------------------------------------------------------------
    # 1. Remap referencias al estado eliminado: 1780942815469 → 1780942843788
    # -----------------------------------------------------------------------
    conn.execute(sa.text(
        "UPDATE viv_cordon_cuneta SET ejuridico=1780942843788 WHERE ejuridico=1780942815469"
    ))
    conn.execute(sa.text(
        "UPDATE viv_cordon_cuneta SET etecnico=1780942843788 WHERE etecnico=1780942815469"
    ))
    conn.execute(sa.text(
        "UPDATE viv_cordon_cuneta SET efinanciero=1780942843788 WHERE efinanciero=1780942815469"
    ))

    # -----------------------------------------------------------------------
    # 2. Actualizar estados CC existentes (label, bg, text_color, orden)
    # -----------------------------------------------------------------------
    for eid, label, bg, text_color, orden in CC_ESTADOS_UPDATE:
        conn.execute(sa.text(
            "UPDATE viv_cc_estados SET label=:label, bg=:bg, text_color=:tc, orden=:orden WHERE id=:id"
        ), {"label": label, "bg": bg, "tc": text_color, "orden": orden, "id": eid})

    # Eliminar estado obsoleto
    conn.execute(sa.text("DELETE FROM viv_cc_estados WHERE id=1780942815469"))

    # Insertar 2 nuevos estados CC
    for eid, label, bg, text_color, orden in CC_ESTADOS_NEW:
        conn.execute(sa.text(
            "INSERT INTO viv_cc_estados (id, label, bg, text_color, orden, aplica_juridico, aplica_tecnico, aplica_financiero) "
            "VALUES (:id, :label, :bg, :tc, :orden, true, true, true)"
        ), {"id": eid, "label": label, "bg": bg, "tc": text_color, "orden": orden})

    # -----------------------------------------------------------------------
    # 3. Actualizar 46 municipios CC existentes (por expediente)
    # -----------------------------------------------------------------------
    for row in CC_MUNICIPIOS_UPDATE:
        (exp, municipio, depto, cc_ml, adq_m2, ok_gob, doc_exp,
         ejuridico, etecnico, efinanciero, obs) = row
        conn.execute(sa.text("""
            UPDATE viv_cordon_cuneta SET
                municipio=:municipio, departamento=:depto,
                cordon_cuneta_ml=:cc_ml, adoquinado_m2=:adq_m2,
                ok_gob=:ok_gob, doc_exp=:doc_exp,
                ejuridico=:ej, etecnico=:et, efinanciero=:ef,
                obs=:obs
            WHERE expediente=:exp AND deleted_at IS NULL
        """), {
            "municipio": municipio, "depto": depto,
            "cc_ml": cc_ml, "adq_m2": adq_m2,
            "ok_gob": ok_gob, "doc_exp": doc_exp,
            "ej": ejuridico, "et": etecnico, "ef": efinanciero,
            "obs": obs, "exp": exp,
        })

    # -----------------------------------------------------------------------
    # 4. Insertar 8 nuevos municipios CC
    # -----------------------------------------------------------------------
    for row in CC_MUNICIPIOS_NEW:
        (orden, municipio, depto, exp, monto, cc_ml, adq_m2,
         ok_gob, doc_exp, ejuridico, etecnico, efinanciero, obs) = row
        conn.execute(sa.text("""
            INSERT INTO viv_cordon_cuneta
                (id, orden, municipio, departamento, expediente, monto,
                 cordon_cuneta_ml, adoquinado_m2, ok_gob, doc_exp,
                 ejuridico, etecnico, efinanciero, obs,
                 created_at, updated_at)
            VALUES
                (:id, :orden, :municipio, :depto, :exp, :monto,
                 :cc_ml, :adq_m2, :ok_gob, :doc_exp,
                 :ej, :et, :ef, :obs,
                 NOW(), NOW())
        """), {
            "id": str(_uuid.uuid4()), "orden": orden,
            "municipio": municipio, "depto": depto, "exp": exp, "monto": monto,
            "cc_ml": cc_ml, "adq_m2": adq_m2, "ok_gob": ok_gob, "doc_exp": doc_exp,
            "ej": ejuridico, "et": etecnico, "ef": efinanciero, "obs": obs,
        })

    # -----------------------------------------------------------------------
    # 5. Calcular estado_general para CC (estado con menor orden entre las 3 dims)
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        UPDATE viv_cordon_cuneta cc
        SET estado_general = (
            SELECT id FROM viv_cc_estados
            WHERE id = ANY(ARRAY_REMOVE(ARRAY[cc.ejuridico, cc.etecnico, cc.efinanciero], NULL))
            ORDER BY orden ASC
            LIMIT 1
        )
        WHERE deleted_at IS NULL
    """))

    # -----------------------------------------------------------------------
    # 6. CH: actualizar TALA CAÑADA y PASO VIEJO
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        UPDATE viv_cordoba_hogar
        SET ejuridico=6,
            obs='2/7 llega doc legal, se devuelven observaciones'
        WHERE localidad='TALA CAÑADA' AND departamento='Pocho' AND deleted_at IS NULL
    """))
    conn.execute(sa.text("""
        UPDATE viv_cordoba_hogar
        SET ejuridico=6,
            obs='2/7 Se solicita la geolocalizacion en direccion s/n - Firmas Pegadas'
        WHERE localidad='PASO VIEJO' AND departamento='Cruz del Eje' AND deleted_at IS NULL
    """))

    # -----------------------------------------------------------------------
    # 7. Insertar nueva localidad CH: LAS HIGUERAS
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        INSERT INTO viv_cordoba_hogar
            (id, orden, localidad, departamento, fecha_anuncio, expediente,
             monto, cantidad_casas, ok_gob, doc_exp,
             ejuridico, etecnico, efinanciero, obs,
             created_at, updated_at)
        VALUES
            (:id, 44, 'LAS HIGUERAS', 'Río Cuarto', NULL, '077284011105626',
             0, NULL, 'SI', 'Intendente solicita Viviendas',
             1, 1, 1, '3/7 se pasa para V.B',
             NOW(), NOW())
    """), {"id": str(_uuid.uuid4())})

    # -----------------------------------------------------------------------
    # 8. Calcular estado_general para CH
    # -----------------------------------------------------------------------
    conn.execute(sa.text("""
        UPDATE viv_cordoba_hogar ch
        SET estado_general = (
            SELECT id FROM viv_ch_estados
            WHERE id = ANY(ARRAY_REMOVE(ARRAY[ch.ejuridico, ch.etecnico, ch.efinanciero], NULL))
            ORDER BY orden ASC
            LIMIT 1
        )
        WHERE deleted_at IS NULL
    """))

    # -----------------------------------------------------------------------
    # 9. Seed geo_localidades desde JSON
    # -----------------------------------------------------------------------
    geo_path = os.path.normpath(os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..",
        "docs", "data", "geo_localidades.json"
    ))
    with open(geo_path, encoding="utf-8") as f:
        geo_data = json.load(f)

    for loc in geo_data:
        conn.execute(sa.text("""
            INSERT INTO viv_geo_localidades (id_geo, departamento, localidad, lat_centro, lon_centro, activo)
            VALUES (:id_geo, :departamento, :localidad, :lat_centro, :lon_centro, :activo)
            ON CONFLICT (id_geo) DO NOTHING
        """), {
            "id_geo": str(loc.get("id_geo", "")),
            "departamento": loc.get("departamento", ""),
            "localidad": loc.get("localidad", ""),
            "lat_centro": loc.get("lat_centro"),
            "lon_centro": loc.get("lon_centro"),
            "activo": loc.get("activo", True),
        })


def downgrade() -> None:
    # No se implementa downgrade para migraciones de datos
    pass
