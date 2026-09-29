# svc-datos-externos

Datos de referencia externos (Censo 2022 INDEC a nivel gobierno local +
transferencias automáticas a municipios/comunas de `transparencia.cba.gov.ar`).
Federa en `resumen_territorial` de `svc-vivienda` como quinta fuente (ADR-025).

Sin panel de negocio ni endpoints públicos — v1 es exclusivamente `app/internal/router.py`
(IAM-only, no pasa por API Gateway). Ver `docs/files/spec-resumen-territorial-tablero-v2.md`.

## Setup

```bash
pip install -e ".[dev]"
pytest
```

## Correr local

```bash
docker-compose -f docker-compose.dev.yml up
# API en :8005, Postgres en :5436
```

```bash
alembic upgrade head   # crea el esquema + carga el Censo 2022 (migración 0002)
```

La migración `0002` carga `docs/data/c2022_cordoba_gobierno_local_c1 (5).xlsx`
y resuelve `id_geo` contra `docs/data/geo_localidades.json` sin red — no
depende de que `svc-vivienda` esté levantado. Resultado esperado (validado en
la sesión de diseño): 427 filas, ~93% con match confiable (exacto o fuzzy),
~7% (`ambiguo`/`sin_match`) para revisión manual — mismo criterio tolerante
que el resto del sistema, no bloquea la carga.

## Endpoints internos (IAM-only, `app/internal/router.py`)

```
GET  /internal/datos-externos/rollup-territorial
POST /internal/datos-externos/transferencias/sync?tipo=municipio&periodo=2026-07-01
POST /internal/datos-externos/transferencias/cargar-manual   (multipart, respaldo)
GET  /internal/datos-externos/transferencias/sync-estado
```

## ETL de transferencias

`app/transferencias/extract.py` contiene el parser de PDF (posicional por
columna, no por heurística de texto — ver los comentarios en el código para
las 3 anomalías reales ya resueltas: nombre con dígito, colisión de prefijo
"TOTAL GENERAL"/"TOTAL General Roca", y un TOTAL mal rotulado en la fuente
original). `app/transferencias/pdf_source.py` descubre y descarga el PDF del
período (el sitio bloquea clientes sin user-agent de navegador).
`app/transferencias/sync.py` orquesta: extraer → validar sumas → resolver
`id_geo` en batch contra `svc-vivienda` (`RESOLVER_LOCALIDADES_ENABLED=true` +
`SVC_VIVIENDA_INTERNAL_URL`) → upsert con `SAVEPOINT` por fila → log de corrida.

Sin `RESOLVER_LOCALIDADES_ENABLED=true`, todas las filas quedan con
`id_geo=NULL` (no bloquea la carga) — necesario para probar contra un
`svc-vivienda` local levantado en `:8001` con el endpoint
`POST /internal/geo/resolver-localidades` (ADR-024) alcanzable.
