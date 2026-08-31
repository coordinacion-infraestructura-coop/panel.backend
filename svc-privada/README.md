# svc-privada

Microservicio de la Secretaría Privada del Ministro — gestión de demandas/gestiones.
Migrado desde el sistema externo en BigQuery (`essential-haiku-482815-u4`) al monorepo
sobre PostgreSQL (**ADR-008**). Patrón panel-module (**ADR-009**).

**Specs**: `docs/files/spec-migracion-svc-privada.md` (approved v1.0.0) + specs hijos
(`spec-privada-categorias-programas.md`, `spec-privada-flujo-derivaciones.md`,
`spec-privada-tablero.md`, `spec-resumen-territorial-ficha-localidad.md`,
`spec-privada-informe-cooperativas-v2.md`).
**Checklist**: `docs/files/TODO-migracion-svc-privada.md`.

## Estado

**Fase 1 (scaffold + schema).** Estructura del servicio + `app/` core (config, database,
auth, audit, main) + Alembic `0001` con el schema `priv_*` de paridad. Sin routers todavía
(Fase 2). El contrato `/api/v1/privada/**` lo sigue sirviendo el backend externo hasta el
cutover.

## Desarrollo local

```bash
# desde services/svc-privada/
pip install -e ".[dev]"

# tests (SQLite in-memory, sin Postgres)
pytest

# stack local con Docker (API en :8002, Postgres en :5433 — distintos de svc-vivienda)
docker-compose -f docker-compose.dev.yml up

# migraciones (siempre desde services/svc-privada/, nunca desde la raíz)
alembic upgrade head
alembic current
```

## Auth (ADR-015)

`app/auth.py` valida el JWT de Firebase (`X-Forwarded-Authorization`) y resuelve rol +
secretarías consultando `portal_usuarios` — que vive en `db_vivienda` — vía el endpoint
interno IAM-only `GET {SVC_VIVIENDA_INTERNAL_URL}/internal/portal/usuarios/{email}` de
svc-vivienda. En dev (`SVC_VIVIENDA_INTERNAL_URL` vacío) el lookup degrada a rol
`invitado`. El endpoint interno se implementa en svc-vivienda en la Fase 3.

## Convenciones

- Tablas prefijadas `priv_`, soft delete `deleted_at`, Alembic only.
- `estado` es `VARCHAR` + `CHECK` (no ENUM), sin validación de transición (ADR-009).
- Concurrencia por lock optimista sobre `updated_at` → `409`.
- `estado = FINALIZADA` setea `fecha_finalizacion` (corrige un bug del sistema viejo).
- Audit log en toda escritura (`app/audit.py`, tabla `priv_audit_log`, write-only).
