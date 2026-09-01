#!/usr/bin/env bash
# =============================================================================
# obtener_anexo_D.sh — captura respuestas reales del sistema viejo (fixtures de
# tests de contrato para la migración de svc-privada).
# =============================================================================
# Requiere:  export TOKEN="<ID token de Firebase>"   (ver README / paso 1)
#            NO editar el token dentro de este archivo — pasarlo por entorno.
#
# Pega DIRECTO al Cloud Run viejo con el header X-Forwarded-Authorization (el
# `require_user` del backend viejo lo valida igual que si viniera del gateway).
# Así también capturamos los 4 /informe/cooperativas/* que por el gateway dan 404.
#
# Escribe en ../anexos/D/  (gitignored). Todo GET, no escribe nada en prod.
# Compatible con sh (sin `pipefail`, sin arrays). Igual conviene correrlo con bash.
# =============================================================================
set -eu

if [ -z "${TOKEN:-}" ]; then
  echo "ERROR: falta el token. Corre:  export TOKEN='eyJ...'  y volve a ejecutar." >&2
  exit 1
fi

BASE="${BASE:-https://infraestructura-gestioninterna-354063050046.southamerica-east1.run.app}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/anexos/D"
mkdir -p "$OUT"

# get <archivo> <path> [args extra para curl -G, p.ej. --data-urlencode "k=v"]
get() {
  _f="$1"; _path="$2"; shift 2
  echo "  -> $_f"
  if curl -sS -G "$@" \
        -H "X-Forwarded-Authorization: Bearer $TOKEN" \
        -H "Accept: application/json" \
        "$BASE$_path" > "$OUT/$_f.raw" 2>/dev/null; then
    if python -m json.tool < "$OUT/$_f.raw" > "$OUT/$_f" 2>/dev/null; then
      rm -f "$OUT/$_f.raw"
    else
      mv "$OUT/$_f.raw" "$OUT/$_f"
      echo "     (respuesta no-JSON, guardada cruda)"
    fi
  else
    echo "     (curl fallo para $_path)" >&2
  fi
}

echo ">>> host: $BASE"
echo ">>> out:  $OUT"

# ── Listado + un detalle real ───────────────────────────────────────────────
get gestiones_list.json           /api/v1/privada/gestiones --data-urlencode "limit=5"
get gestiones_list_filtrada.json  /api/v1/privada/gestiones \
    --data-urlencode "limit=5" --data-urlencode "estado=FINALIZADA"

GID=$(python -c "import json;d=json.load(open('$OUT/gestiones_list.json'));print(d['items'][0]['id_gestion'])" 2>/dev/null || true)
DEP=$(python -c "import json;d=json.load(open('$OUT/gestiones_list.json'));print(d['items'][0]['departamento'])" 2>/dev/null || true)
LOC=$(python -c "import json;d=json.load(open('$OUT/gestiones_list.json'));print(d['items'][0]['localidad'])" 2>/dev/null || true)
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
echo "    (POST /gestiones y /cambiar-estado NO se capturan: son escrituras; su forma se documenta del codigo.)"
