# svc-gralgob — Fase 0: sync de solo lectura del Sheet "ATP - Compromiso Gobernador"

Servicio de la Secretaría General de Gobierno. **No estaba en el plan
original** — se agrega el 2026-09-21 a pedido del usuario. Esta primera
versión **no es el ABM de negocio** — es solo el módulo de sincronización
(espejo de solo lectura del Google Sheet que hoy mantiene el área), siguiendo
el mismo patrón que el sync de Gasifera (`svc-gasifera`) y el de Checklist
Técnico de Cordón Cuneta en `svc-vivienda`.

Ver specs:
- `docs/files/spec-sync-atp-compromiso-gobernador.md` (esta entrega — sync, `approved`)
- `docs/files/spec-svc-gralgob.md` (dominio completo del futuro ABM — `draft`, no implementado aún)

## Qué hace hoy

Un único endpoint interno (IAM-only, no pasa por API Gateway) que lee la
hoja `BD` del Sheet real (compromisos de **ATP — Aporte del Tesoro
Provincial**, y su cronograma de pago mensual) y la espeja en Postgres:

- `POST /internal/sync/atp-compromiso-gobernador` — corre la sincronización.
- `GET /internal/sync/atp-compromiso-gobernador/estado` — última corrida (`atp_sync_log`).

No hay endpoints de negocio, no hay auth de usuario (`app/auth.py` no existe
en esta fase), no hay frontend.

## Setup

```bash
pip install -e ".[dev]"
pytest                    # SQLite in-memory, no requiere Postgres
```

## Correr localmente contra Postgres real

```bash
docker-compose -f docker-compose.dev.yml up -d db
alembic upgrade head
uvicorn app.main:app --reload --port 8004
```

### Autenticación contra el Google Sheet (ADC)

El cliente (`app/integrations/google_sheets.py`) usa **Application Default
Credentials** — no hay claves ni `.env` con secretos. Para probarlo en local:

```bash
gcloud auth application-default login   # con una cuenta que tenga acceso Viewer al Sheet
```

Completar en `.env` (no se commitea, ver `.gitignore` de `services/`):

```
GOOGLE_SHEET_ATP_ID=1x3E73hlGwDPBiLc9fbQuWxWUxjaibs3glModHsxCMZM
```

Luego:

```bash
curl -X POST http://localhost:8004/internal/sync/atp-compromiso-gobernador
```

Debería traer ~1110 compromisos (`atp_compromisos`) — mismo conteo que el
análisis del Excel
(`docs/context/areas/secretaria_Gral_Gobierno/ATP - Compromiso Gobernador.xlsx`,
hoja `BD`, filas 6-1115 al momento del análisis).

Cuando esto se despliegue de verdad (fuera de esta entrega, vía skill
`/deploy-servicio`), el Sheet se comparte como Viewer con la Service Account
de runtime de `svc-gralgob` en Cloud Run, igual que el resto de los
servicios.

## Fuera de alcance de esta fase

- Deploy real (Cloud SQL `db_gralgob`, Cloud Run, Cloud Scheduler, IAM).
- Cualquier endpoint de negocio (`/api/v1/gralgob/**`), `app/auth.py`,
  integración con `portal_usuarios`.
- Frontend.
- La hoja `Estado de exp` (seguimiento de expedientes — entidad separada) y
  los otros programas de fondos del mismo libro (`ATP ACUMULADO`,
  `COPA+FOFINDES`, `SALDO`, `BD NATALIO`) — no son "ATP - Compromiso
  Gobernador". Ver `docs/context/areas/secretaria_Gral_Gobierno/contexto_detallado.md §2`.
- Federación de estas líneas hacia `resumen_territorial` (svc-vivienda) —
  requiere spec/ADR propio, mismo patrón que ADR-016 usó para Privada.
