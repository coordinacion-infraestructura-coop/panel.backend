-- GENERADO por sql/generar_grants.py — no editar a mano.
-- Correr como postgres; cada bloque contra su base (\connect).

\connect db_vivienda
GRANT CONNECT ON DATABASE db_vivienda TO agente_ro;
GRANT USAGE ON SCHEMA public TO agente_ro;
ALTER ROLE agente_ro SET default_transaction_read_only = on;
GRANT SELECT (campo, created_at, estado_anterior_id, estado_nuevo_id, id, municipio_id) ON viv_cc_estado_historial TO agente_ro;
GRANT SELECT (id, label) ON viv_cc_estados TO agente_ro;
GRANT SELECT (campo, created_at, estado_anterior_id, estado_nuevo_id, id, localidad_id) ON viv_ch_estado_historial TO agente_ro;
GRANT SELECT (id, label) ON viv_ch_estados TO agente_ro;
GRANT SELECT (checklist_id, deleted_at, fecha_medicion, porcentaje) ON viv_checklist_avance_medicion TO agente_ro;
GRANT SELECT (id, label) ON viv_checklist_estado_expediente TO agente_ro;
GRANT SELECT (checklist_id, created_at, estado_expediente_id, id) ON viv_checklist_estado_hist TO agente_ro;
GRANT SELECT (checklist_id, fecha_acreditado, id, tipo) ON viv_checklist_obra_hitos TO agente_ro;
GRANT SELECT (entidad_id, estado_expediente_id, id, programa) ON viv_checklist_tecnico TO agente_ro;
GRANT SELECT (cantidad_casas, deleted_at, departamento, estado_general, fecha_anuncio, id, localidad, localidad_id, monto, updated_at) ON viv_cordoba_hogar TO agente_ro;
GRANT SELECT (deleted_at, departamento, estado_general, id, localidad_id, monto, municipio, updated_at) ON viv_cordon_cuneta TO agente_ro;
GRANT SELECT (deleted_at, departamento_normalizado, id, id_geo, texto_normalizado) ON viv_geo_alias_manual TO agente_ro;
GRANT SELECT (activo, departamento, id_geo, lat_centro, localidad, lon_centro) ON viv_geo_localidades TO agente_ro;
GRANT SELECT (campo, created_at, estado_anterior_id, estado_nuevo_id, id, proyecto_id) ON viv_ml_estado_historial TO agente_ro;
GRANT SELECT (id, label) ON viv_ml_estados TO agente_ro;
GRANT SELECT (deleted_at, departamento, estado_general, id, localidad_id, lotes, monto, nombre, updated_at) ON viv_ml_proyectos TO agente_ro;

\connect db_privada
GRANT CONNECT ON DATABASE db_privada TO agente_ro;
GRANT USAGE ON SCHEMA public TO agente_ro;
ALTER ROLE agente_ro SET default_transaction_read_only = on;
GRANT SELECT (id, label) ON priv_areas TO agente_ro;
GRANT SELECT (id, nombre) ON priv_cat_categoria_general TO agente_ro;
GRANT SELECT (id, nombre) ON priv_cat_ministerio_agencia TO agente_ro;
GRANT SELECT (id, label) ON priv_categorias TO agente_ro;
GRANT SELECT (area_id, canal_origen, categoria_general_id, categoria_id, costo_estimado, deleted_at, departamento, detalle, estado, fecha_estado, fecha_finalizacion, fecha_ingreso, geo_id, id, localidad, ministerio_agencia_id, ok_gobernador, ok_ministro, programa_id, tipo_gestion, urgencia) ON priv_gestiones TO agente_ro;
GRANT SELECT (estado_anterior, estado_nuevo, fecha_evento, gestion_id, id) ON priv_gestiones_eventos TO agente_ro;
GRANT SELECT (id_geo, intendente_jefe_comunal, partido_politico) ON priv_localidades_info TO agente_ro;
GRANT SELECT (id, label) ON priv_programas TO agente_ro;

\connect db_gasifera
GRANT CONNECT ON DATABASE db_gasifera TO agente_ro;
GRANT USAGE ON SCHEMA public TO agente_ro;
ALTER ROLE agente_ro SET default_transaction_read_only = on;
GRANT SELECT (accion, departamento, estado, fecha, id, id_geo, localidad, monto_inversion_solicitado, monto_inversion_usd, updated_at) ON gas_pit_acciones_territorio TO agente_ro;
GRANT SELECT (avance, departamento, estado_obra, estado_resumen, fecha_lic, id, importe_dolar, importe_obra_actualizado, nombre_obra, updated_at) ON gas_pit_obras TO agente_ro;
GRANT SELECT (id_geo, localidad, obra_id) ON gas_pit_obras_localidades TO agente_ro;
GRANT SELECT (finished_at) ON gas_pit_sync_log TO agente_ro;

\connect db_gralgob
GRANT CONNECT ON DATABASE db_gralgob TO agente_ro;
GRANT USAGE ON SCHEMA public TO agente_ro;
ALTER ROLE agente_ro SET default_transaction_read_only = on;
GRANT SELECT (departamento, destino, fecha_anuncio, id, id_geo, localidad, monto, updated_at) ON atp_compromisos TO agente_ro;
GRANT SELECT (compromiso_id, id, monto, periodo) ON atp_cronograma_pagos TO agente_ro;
GRANT SELECT (codigo_indec, departamento, fecha, id, localidad, monto) ON atp_interno_pagos TO agente_ro;
GRANT SELECT (finished_at) ON atp_sync_log TO agente_ro;

\connect db_datos_externos
GRANT CONNECT ON DATABASE db_datos_externos TO agente_ro;
GRANT USAGE ON SCHEMA public TO agente_ro;
ALTER ROLE agente_ro SET default_transaction_read_only = on;
GRANT SELECT (codigo_indec, deleted_at, id_geo, poblacion_2022, viviendas_2022) ON ext_geo_censo TO agente_ro;
GRANT SELECT (concepto, departamento_pdf, id, id_geo, monto, nombre_pdf, periodo, tipo) ON ext_transferencias TO agente_ro;
GRANT SELECT (corrida_en) ON ext_transferencias_sync_log TO agente_ro;
