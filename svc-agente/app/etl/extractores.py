"""Consultas de extracción por fuente (spec §2.2 plan B, §4).

Cada consulta lista columnas explícitas: nunca `SELECT *`. Las columnas con datos personales
(spec §4) no aparecen acá, y además el rol `agente_ro` no tiene GRANT sobre ellas
(sql/grants_fuentes.sql) — si alguien agrega una por error, la consulta falla en vez de filtrar
el dato.
"""

VIVIENDA: dict[str, str] = {
    "localidades": """
        SELECT id_geo, departamento, localidad, lat_centro, lon_centro
        FROM viv_geo_localidades WHERE activo = true
    """,
    "alias": """
        SELECT id, texto_normalizado, departamento_normalizado, id_geo
        FROM viv_geo_alias_manual WHERE deleted_at IS NULL
    """,
    "cc": """
        SELECT c.id, c.municipio AS nombre, c.departamento, c.localidad_id AS id_geo, c.monto,
               NULL AS cantidad, eg.label AS estado_general, NULL AS fecha_inicio, c.updated_at
        FROM viv_cordon_cuneta c LEFT JOIN viv_cc_estados eg ON eg.id = c.estado_general
        WHERE c.deleted_at IS NULL
    """,
    "ch": """
        SELECT c.id, c.localidad AS nombre, c.departamento, c.localidad_id AS id_geo, c.monto,
               c.cantidad_casas AS cantidad, eg.label AS estado_general,
               c.fecha_anuncio AS fecha_inicio, c.updated_at
        FROM viv_cordoba_hogar c LEFT JOIN viv_ch_estados eg ON eg.id = c.estado_general
        WHERE c.deleted_at IS NULL
    """,
    "ml": """
        SELECT p.id, p.nombre, p.departamento, p.localidad_id AS id_geo, p.monto,
               p.lotes AS cantidad, eg.label AS estado_general, NULL AS fecha_inicio, p.updated_at
        FROM viv_ml_proyectos p LEFT JOIN viv_ml_estados eg ON eg.id = p.estado_general
        WHERE p.deleted_at IS NULL
    """,
    "checklist": """
        SELECT ct.id, ct.programa, ct.entidad_id, ee.label AS estado_expediente
        FROM viv_checklist_tecnico ct
        LEFT JOIN viv_checklist_estado_expediente ee ON ee.id = ct.estado_expediente_id
    """,
    "avance": """
        SELECT checklist_id, porcentaje, fecha_medicion
        FROM viv_checklist_avance_medicion WHERE deleted_at IS NULL
    """,
    "hitos": """
        SELECT h.id, h.tipo, h.fecha_acreditado, ct.programa, ct.entidad_id
        FROM viv_checklist_obra_hitos h JOIN viv_checklist_tecnico ct ON ct.id = h.checklist_id
    """,
    "hist_cc": """
        SELECT h.id, h.municipio_id AS origen_id, h.campo, ea.label AS anterior,
               en.label AS nuevo, h.created_at AS fecha
        FROM viv_cc_estado_historial h
        LEFT JOIN viv_cc_estados ea ON ea.id = h.estado_anterior_id
        LEFT JOIN viv_cc_estados en ON en.id = h.estado_nuevo_id
    """,
    "hist_ch": """
        SELECT h.id, h.localidad_id AS origen_id, h.campo, ea.label AS anterior,
               en.label AS nuevo, h.created_at AS fecha
        FROM viv_ch_estado_historial h
        LEFT JOIN viv_ch_estados ea ON ea.id = h.estado_anterior_id
        LEFT JOIN viv_ch_estados en ON en.id = h.estado_nuevo_id
    """,
    "hist_ml": """
        SELECT h.id, h.proyecto_id AS origen_id, h.campo, ea.label AS anterior,
               en.label AS nuevo, h.created_at AS fecha
        FROM viv_ml_estado_historial h
        LEFT JOIN viv_ml_estados ea ON ea.id = h.estado_anterior_id
        LEFT JOIN viv_ml_estados en ON en.id = h.estado_nuevo_id
    """,
    "hist_checklist": """
        SELECT h.id, ct.programa, ct.entidad_id AS origen_id, ee.label AS nuevo,
               h.created_at AS fecha
        FROM viv_checklist_estado_hist h
        JOIN viv_checklist_tecnico ct ON ct.id = h.checklist_id
        LEFT JOIN viv_checklist_estado_expediente ee ON ee.id = h.estado_expediente_id
    """,
}

# Sin direccion/lat/lon/created_by/updated_by/observaciones (spec §4).
PRIVADA: dict[str, str] = {
    "gestiones": """
        SELECT g.id, g.estado, g.urgencia, g.fecha_ingreso, g.fecha_estado, g.fecha_finalizacion,
               g.geo_id AS id_geo, g.departamento, g.localidad, g.tipo_gestion, g.canal_origen,
               g.ok_gobernador, g.ok_ministro, g.costo_estimado, g.detalle,
               a.label AS area, m.nombre AS ministerio, c.label AS categoria,
               cg.nombre AS categoria_general, p.label AS programa
        FROM priv_gestiones g
        LEFT JOIN priv_areas a ON a.id = g.area_id
        LEFT JOIN priv_cat_ministerio_agencia m ON m.id = g.ministerio_agencia_id
        LEFT JOIN priv_categorias c ON c.id = g.categoria_id
        LEFT JOIN priv_cat_categoria_general cg ON cg.id = g.categoria_general_id
        LEFT JOIN priv_programas p ON p.id = g.programa_id
        WHERE g.deleted_at IS NULL
    """,
    # Sin usuario/rol_usuario/comentario/valor_anterior/valor_nuevo (spec §4).
    "eventos": """
        SELECT e.id, e.gestion_id AS origen_id, e.estado_anterior AS anterior,
               e.estado_nuevo AS nuevo, e.fecha_evento AS fecha
        FROM priv_gestiones_eventos e WHERE e.estado_nuevo IS NOT NULL
    """,
    # Padrón político combinado Gobierno + Privada (ADR-027, sync diario).
    "padron": """
        SELECT id_geo, intendente_jefe_comunal AS intendente, partido_politico AS partido
        FROM priv_localidades_info WHERE id_geo IS NOT NULL
    """,
}

GASIFERA: dict[str, str] = {
    "obras": """
        SELECT o.id, o.nombre_obra AS nombre, o.departamento, o.estado_obra, o.estado_resumen,
               o.avance, o.fecha_lic AS fecha_inicio, o.importe_obra_actualizado AS monto,
               o.importe_dolar AS monto_usd, o.updated_at
        FROM gas_pit_obras o
    """,
    "obras_localidades": """
        SELECT obra_id, localidad, id_geo FROM gas_pit_obras_localidades
    """,
    "acciones": """
        SELECT a.id, a.accion AS nombre, a.departamento, a.localidad, a.id_geo, a.estado,
               a.fecha AS fecha_inicio, a.monto_inversion_solicitado AS monto,
               a.monto_inversion_usd AS monto_usd, a.updated_at
        FROM gas_pit_acciones_territorio a
    """,
    "sync": "SELECT MAX(finished_at) AS ultimo FROM gas_pit_sync_log",
}

# Sin atp_interno_pagos.referente (spec §4).
GRALGOB: dict[str, str] = {
    "compromisos": """
        SELECT c.id, c.destino AS nombre, c.departamento, c.localidad, c.id_geo, c.monto,
               c.fecha_anuncio AS fecha_inicio, c.updated_at
        FROM atp_compromisos c
    """,
    "cronograma": """
        SELECT id, compromiso_id, periodo, monto FROM atp_cronograma_pagos
    """,
    "interno": """
        SELECT id, codigo_indec, localidad, departamento, fecha, monto FROM atp_interno_pagos
    """,
    "sync": "SELECT MAX(finished_at) AS ultimo FROM atp_sync_log",
}

DATOS_EXTERNOS: dict[str, str] = {
    "censo": """
        SELECT id_geo, codigo_indec, poblacion_2022, viviendas_2022
        FROM ext_geo_censo WHERE deleted_at IS NULL
    """,
    "transferencias": """
        SELECT id, id_geo, departamento_pdf AS departamento, nombre_pdf AS localidad, tipo,
               concepto, periodo, monto
        FROM ext_transferencias
    """,
    "sync": "SELECT MAX(corrida_en) AS ultimo FROM ext_transferencias_sync_log",
}

FUENTES: dict[str, dict[str, str]] = {
    "vivienda": VIVIENDA,
    "privada": PRIVADA,
    "gasifera": GASIFERA,
    "gralgob": GRALGOB,
    "datos_externos": DATOS_EXTERNOS,
}
