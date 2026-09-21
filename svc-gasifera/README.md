# svc-gasifera — Fase 0: sync de solo lectura del Sheet "SEC. GAS PIT"

Servicio de la Secretaría de Infraestructura Gasífera. **Esta primera versión NO
es el panel de negocio** — es solo el módulo de sincronización (espejo de solo
lectura del Google Sheet que hoy mantiene el área), siguiendo el mismo patrón
que el sync de Checklist Técnico de Cordón Cuneta en `svc-vivienda`.

Ver specs:
- `docs/files/spec-sync-gasifera-pit.md` (esta entrega — sync)
- `docs/files/spec-svc-gasifera.md` (dominio completo del futuro panel — no implementado aún)

## Qué hace hoy

Un único endpoint interno (IAM-only, no pasa por API Gateway) que lee dos
pestañas del Sheet real y las espeja en Postgres:

- `POST /internal/sync/gasifera-pit` — corre la sincronización.
- `GET /internal/sync/gasifera-pit/estado` — última corrida (`gas_pit_sync_log`).

No hay endpoints de negocio, no hay auth de usuario (`app/auth.py` no existe en
esta fase), no hay frontend.

## Setup

```bash
pip install -e ".[dev]"
pytest                    # SQLite in-memory, no requiere Postgres
```

## Correr localmente contra Postgres real

```bash
docker-compose -f docker-compose.dev.yml up -d db
alembic upgrade head
uvicorn app.main:app --reload --port 8003
```

### Autenticación contra el Google Sheet (ADC)

El cliente (`app/integrations/google_sheets.py`) usa **Application Default
Credentials** — no hay claves ni `.env` con secretos. Para probarlo en local:

```bash
gcloud auth application-default login   # con una cuenta que tenga acceso Viewer al Sheet
```

Completar en `.env` (no se commitea, ver `.gitignore` de `services/`):

```
GOOGLE_SHEET_GAS_PIT_ID=<el id del Sheet real>
```

Luego:

```bash
curl -X POST http://localhost:8003/internal/sync/gasifera-pit
```

Debería traer ~17 obras de gas (`gas_pit_obras`) y ~299 acciones territoriales
(`gas_pit_acciones_territorio`) — mismos conteos que el análisis del Excel
(`docs/context/areas/secretaria_Gasifera/SEC. GAS PIT.xlsx`).

Cuando esto se despliegue de verdad (fuera de esta entrega, vía skill
`/deploy-servicio`), el Sheet se comparte como Viewer con la Service Account de
runtime de `svc-gasifera` en Cloud Run, igual que el resto de los servicios.

## Fuera de alcance de esta fase

- Deploy real (Cloud SQL `db_gasifera`, Cloud Run, Cloud Scheduler, IAM).
- Cualquier endpoint de negocio (`/api/v1/gasifera/**`), `app/auth.py`, integración con `portal_usuarios`.
- Frontend.
- Las otras 4 categorías de obra del Sheet (vial, agua/cloaca, eléctrica, arquitectura) — pertenecen a una futura `svc-infraestructura`.
