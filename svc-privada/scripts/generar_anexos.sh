#!/usr/bin/env bash
# =============================================================================
# generar_anexos.sh — dumps del sistema origen para la migración de svc-privada
# =============================================================================
# Corre en Cloud Shell (o local con `bq`/`gcloud`) LOGUEADO a la cuenta dueña
# de essential-haiku-482815-u4. Escribe en ../anexos/ (gitignored).
#
# Genera: Anexo B (catálogos), C (usuarios · PII), F (taxonomía de áreas),
# G (muestras de metadata_json), schemas de las tablas y la línea base del ETL.
#
# Anexo A  (v_informe_cooperativas.sql)  -> ya en anexos/, es el informe de Cooperativas.
# Anexo A2 (resumen_territorial.sql)     -> ya en anexos/, documenta la lógica inline.
# Anexo D  (fixtures de respuestas)      -> aparte: necesita token Firebase (ver README).
# Anexo E  (categoría->programa->área)   -> input de la reunión de relevamiento.
#
# Re-ejecutable: sobrescribe los archivos. Correr de nuevo para el delta del cutover.
# =============================================================================
set -euo pipefail

PROJ="${PROJ:-essential-haiku-482815-u4}"
DS="${DS:-infra_gestion}"
LOC="${LOC:-southamerica-east1}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/anexos"
mkdir -p "$OUT"

BQ=(bq query --location="$LOC" --project_id="$PROJ" --use_legacy_sql=false --max_rows=1000000 --format=prettyjson)

echo ">>> proyecto=$PROJ dataset=$DS  ->  $OUT"
gcloud config set project "$PROJ" >/dev/null

# ── Anexo A (refresco / verificación) ────────────────────────────────────────
bq show --format=prettyjson "$PROJ:$DS.v_informe_cooperativas" \
  | python -c "import sys,json;print(json.load(sys.stdin)['view']['query'])" \
  > "$OUT/A_v_informe_cooperativas.sql" || echo "  (no se pudo refrescar Anexo A)"

# ── Anexo B — catálogos (seed de priv_cat_*) ─────────────────────────────────
for T in cat_estado cat_urgencia cat_ministerio_agencia cat_categoria_general cat_tipo_gestion cat_canal_origen; do
  "${BQ[@]}" "SELECT * FROM \`$PROJ.$DS.$T\` ORDER BY orden, id" > "$OUT/B_$T.json"
done

# ── Anexo C — usuarios (PII, NO commitear) ───────────────────────────────────
bq query --location="$LOC" --project_id="$PROJ" --use_legacy_sql=false --format=csv \
  "SELECT LOWER(email) email, nombre, rol, activo FROM \`$PROJ.$DS.usuarios_roles\` ORDER BY activo DESC, rol, email" \
  > "$OUT/C_usuarios_roles.csv"
bq query --location="$LOC" --project_id="$PROJ" --use_legacy_sql=false --format=csv \
  "SELECT * FROM \`$PROJ.$DS.usuario_modulos\`" > "$OUT/C_usuario_modulos.csv"
"${BQ[@]}" "SELECT * FROM \`$PROJ.$DS.usuarios_eventos\` ORDER BY ts_evento" > "$OUT/C_usuarios_eventos.json"

# ── Anexo F — taxonomía de áreas (insumo priv_areas + alias, ADR-013) ────────
"${BQ[@]}" "SELECT TRIM(derivado_a_id) valor, COUNT(*) n FROM \`$PROJ.$DS.gestiones\`
            WHERE derivado_a_id IS NOT NULL AND TRIM(derivado_a_id)<>'' GROUP BY 1 ORDER BY n DESC" \
            > "$OUT/F_derivado_a_distinct.json"
"${BQ[@]}" "SELECT TRIM(organismo_id) valor, COUNT(*) n FROM \`$PROJ.$DS.gestiones\`
            WHERE organismo_id IS NOT NULL AND TRIM(organismo_id)<>'' GROUP BY 1 ORDER BY n DESC" \
            > "$OUT/F_organismo_id_distinct.json"
"${BQ[@]}" "SELECT JSON_VALUE(metadata_json,'\$.derivado_a') valor, COUNT(*) n
            FROM \`$PROJ.$DS.gestiones_eventos\` WHERE tipo_evento='CAMBIO_ESTADO'
              AND JSON_VALUE(metadata_json,'\$.derivado_a') IS NOT NULL
            GROUP BY 1 ORDER BY n DESC" > "$OUT/F_metadata_derivado_a_distinct.json"
"${BQ[@]}" "SELECT id, nombre, orden FROM \`$PROJ.$DS.cat_ministerio_agencia\` ORDER BY orden" \
            > "$OUT/F_cat_ministerio_agencia.json"

# ── Anexo G — muestras de metadata_json por tipo_evento ──────────────────────
"${BQ[@]}" "SELECT tipo_evento, COUNT(*) n, ANY_VALUE(TO_JSON_STRING(metadata_json)) ejemplo
            FROM \`$PROJ.$DS.gestiones_eventos\` GROUP BY tipo_evento" > "$OUT/G_por_tipo_evento.json"
"${BQ[@]}" "SELECT tipo_evento, estado_anterior, estado_nuevo, campo_modificado,
                   TO_JSON_STRING(metadata_json) metadata_json
            FROM \`$PROJ.$DS.gestiones_eventos\`
            ORDER BY tipo_evento, fecha_evento LIMIT 200" > "$OUT/G_muestras.json"

# ── Schemas de las tablas (referencia del ETL) ──────────────────────────────
for T in gestiones gestiones_eventos localidades_info departamentos_info geo_localidades \
         usuarios_roles usuarios_eventos usuario_modulos cat_modulos \
         cat_estado cat_urgencia cat_ministerio_agencia cat_categoria_general cat_tipo_gestion cat_canal_origen; do
  bq show --schema --format=prettyjson "$PROJ:$DS.$T" > "$OUT/schema_$T.json"
done

# ── Línea base del ETL (Fase 4) — conteos + agregados de control ─────────────
"${BQ[@]}" "
SELECT 'gestiones_total' k, CAST(COUNT(*) AS STRING) v FROM \`$PROJ.$DS.gestiones\`
UNION ALL SELECT 'gestiones_activas', CAST(COUNTIF(is_deleted=FALSE) AS STRING) FROM \`$PROJ.$DS.gestiones\`
UNION ALL SELECT 'gestiones_finalizadas', CAST(COUNTIF(estado='FINALIZADA') AS STRING) FROM \`$PROJ.$DS.gestiones\`
UNION ALL SELECT 'costo_estimado_sum', CAST(ROUND(SUM(costo_estimado),2) AS STRING) FROM \`$PROJ.$DS.gestiones\` WHERE is_deleted=FALSE
UNION ALL SELECT 'fecha_ingreso_min', CAST(MIN(fecha_ingreso) AS STRING) FROM \`$PROJ.$DS.gestiones\`
UNION ALL SELECT 'fecha_ingreso_max', CAST(MAX(fecha_ingreso) AS STRING) FROM \`$PROJ.$DS.gestiones\`
UNION ALL SELECT 'eventos_total', CAST(COUNT(*) AS STRING) FROM \`$PROJ.$DS.gestiones_eventos\`
UNION ALL SELECT 'localidades_info', CAST(COUNT(*) AS STRING) FROM \`$PROJ.$DS.localidades_info\`
UNION ALL SELECT 'departamentos_info', CAST(COUNT(*) AS STRING) FROM \`$PROJ.$DS.departamentos_info\`
UNION ALL SELECT 'geo_localidades_activas', CAST(COUNTIF(activo=TRUE) AS STRING) FROM \`$PROJ.$DS.geo_localidades\`
ORDER BY k" > "$OUT/ETL_baseline.json"

"${BQ[@]}" "SELECT COUNTIF(estado='FINALIZADA') finalizadas,
                   COUNTIF(estado='FINALIZADA' AND fecha_finalizacion IS NULL) finalizadas_sin_fecha
            FROM \`$PROJ.$DS.gestiones\` WHERE is_deleted=FALSE" > "$OUT/ETL_fecha_finalizacion_gap.json"

# Rollup por (departamento, localidad) — baseline del resumen territorial (Anexo A2)
"${BQ[@]}" "
SELECT UPPER(TRIM(departamento)) departamento, UPPER(TRIM(localidad)) localidad,
       COUNT(*) total_gestiones,
       COUNTIF(UPPER(TRIM(estado)) NOT IN ('FINALIZADA','ARCHIVADO')) abiertas,
       COUNTIF(UPPER(TRIM(estado)) = 'FINALIZADA') finalizadas,
       COUNTIF(LOWER(TRIM(urgencia)) = 'alta') urgentes,
       ROUND(SUM(costo_estimado),2) costo_estimado_sum
FROM \`$PROJ.$DS.gestiones\` WHERE is_deleted=FALSE
GROUP BY departamento, localidad ORDER BY departamento, localidad" \
> "$OUT/A2_rollup_territorial_baseline.json"

echo ">>> listo. Revisar $OUT/  (C_* tiene PII -> no commitear)"
