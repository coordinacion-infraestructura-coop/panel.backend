#!/usr/bin/env bash
# =============================================================================
# obtener_anexo_D.sh — captura respuestas reales del sistema viejo (fixtures de
# tests de contrato para la migración de svc-privada).
# =============================================================================
# Requiere:  export TOKEN="<ID token de Firebase>"   (ver README / paso 1)
#
# Pega DIRECTO al Cloud Run viejo con el header X-Forwarded-Authorization (el
# `require_user` del backend viejo lo valida igual que si viniera del gateway).
# Así también capturamos los 4 /informe/cooperativas/* que por el gateway dan 404.
#
# Escribe en ../anexos/D/  (gitignored). Todo GET, no escribe nada en prod.
# =============================================================================
set -euo pipefail

: "${TOKEN:?export TOKEN=<ID token de Firebase> antes de correr}"
BASE="${BASE:-https://infraestructura-gestioninterna-354063050046.southamerica-east1.run.app}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/anexos/D"
mkdir -p "$OUT"

H=(-H "X-Forwarded-Authorization: Bearer $TOKEN" -H "Accept: application/json")
get() { # get <archivo> <path> [curl -G args...]
  local f="$1"; local path="$2"; shift 2
  echo "  -> $f"
  curl -sS -G "$@" "${H[@]}" "$BASE$path" | python -m json.tool > "$OUT/$f" 2>/dev/null \
    || { curl -sS -G "$@" "${H[@]}" "$BASE$path" > "$OUT/$f"; echo "     (no era JSON, guardado crudo)"; }
}

echo ">>> host: $BASE   ->  $OUT"

# ── Listado + un detalle real ───────────────────────────────────────────────
get gestiones_list.json           /api/v1/privada/gestiones --data-urlencode "limit=5"
get gestiones_list_filtrada.json  /api/v1/privada/gestiones \
    --data-urlencode "limit=5" --data-urlencode "estado=FINALIZADA"

GID=$(python -c "import json;d=json.load(open('$OUT/gestiones_list.json'));print(d['items'][0]['id_gestion'])" 2>/dev/null || echo "")
DEP=$(python -c "import json;d=json.load(open('$OUT/gestiones_list.json'));print(d['items'][0]['departamento'])" 2>/dev/null || echo "")
LOC=$(python -c "import json;d=json.load(open('$OUT/gestiones_list.json'));print(d['items'][0]['localidad'])" 2>/dev/null || echo "")
echo "    gestion=$GID  depto=$DEP  localidad=$LOC"

if [ -n "$GID" ]; then
  get gestion_detalle.json  "/api/v1/privada/gestiones/$GID"
  get gestion_eventos.json  "/api/v1/privada/gestiones/$GID/eventos"
fi

# ── Resumen territorial (2 scopes) + info de localidad ──────────────────────
if [ -n "$DEP" ]; then
  get resumen_depto.json  /api/v1/privada/gestiones/resumen-territorial --data-urlencode "departamento=$DEP"
  if [ -n "$LOC" ]; then
    get resumen_localidad.json  /api/v1/privada/gestiones/resumen-territorial \
        --data-urlencode "departamento=$DEP" --data-urlencode "localidad=$LOC"
    get localidad_info.json  /api/v1/privada/localidades-info \
        --data-urlencode "departamento=$DEP" --data-urlencode "localidad=$LOC"
    get catalogo_geo.json  /api/v1/privada/catalogos/geo \
        --data-urlencode "departamento=$DEP" --data-urlencode "localidad=$LOC"
    get catalogo_localidades.json  /api/v1/privada/catalogos/localidades \
        --data-urlencode "departamento=$DEP"
  fi
fi

# ── Catálogos ──────────────────────────────────────────────────────────────
for C in estados urgencias ministerios categorias tipos-gestion canales-origen departamentos; do
  get "catalogo_$C.json"  "/api/v1/privada/catalogos/$C"
done

# ── Perfil ────────────────────────────────────────────────────────────────
get me.json  /api/v1/privada/me

# ── Informe de Cooperativas — por la ruta LEGACY (el prefijo /api/v1/privada da 404) ──
for R in resumen temporal por-departamento puntos; do
  get "informe_$R.json"  "/informe/cooperativas/$R"
done

echo ">>> listo. Revisar $OUT/  y avisar 'listo D'."
echo "    (POST /gestiones y /cambiar-estado NO se capturan: son escrituras; su forma se documenta del código.)"
