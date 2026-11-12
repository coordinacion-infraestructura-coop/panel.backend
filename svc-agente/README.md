# svc-agente — Agente conversacional de consultas

Chat para que `Admin` y `Autoridad` consulten en lenguaje natural los datos de las cinco
secretarías/servicios. Spec: `docs/files/spec-agente-consultas.md` (approved 1.0.0). ADR-033.

## Cómo funciona

```
POST /api/v1/agente/conversaciones/{id}/mensajes
  └─ loop de tool use (app/agente/llm.py) contra Claude por la API de Anthropic (AsyncAnthropic, API key; Vertex queda como alternativa)
       ├─ resolver_territorio · estado_programa_territorio · ficha_territorio · montos · pendientes
       │     (app/agente/indicadores.py — indicadores prediseñados, spec §5)
       └─ consulta_sql (app/agente/sql_guard.py + rol agente_llm de solo lectura)
                       └─ schema `ag` de db_agente (capa semántica, app/semantica/models.py)
                              ▲ POST /internal/agente/refrescar (Cloud Scheduler, cada hora)
                              │ app/etl/ — lee las 5 bases con el rol agente_ro
```

- **Capa semántica** (`ag.*`): proyección de solo lectura, con `id_geo` y nombres oficiales.
  El refresco reemplaza sólo lo de las fuentes que respondieron; si una falla se conserva el
  último dato bueno y `ag_frescura` lo registra.
- **Glosario** (`app/semantica/glosario.yaml`): sinónimos, mapeo de estados a la escala común,
  definición de "ejecutado", umbrales de demora, descripción de tablas y ejemplos SQL. Es dato:
  cambiarlo no requiere nueva versión del spec. **El mapeo de estados de Vivienda y Gasífera es
  inicial y tiene que revisarlo cada área antes de anunciar el agente.**
- **Datos personales**: excluidos por `GRANT`. `sql/grants_fuentes.sql` se genera desde los
  extractores (`python sql/generar_grants.py > sql/grants_fuentes.sql`); un test falla si no
  coinciden o si un extractor lee una columna excluida.

## Desarrollo

```bash
pip install -e ".[dev]"
pytest                                   # SQLite en archivos temporales, sin Postgres ni Claude
docker-compose -f docker-compose.dev.yml up   # API :8006, Postgres :5437
alembic upgrade head                     # siempre desde svc-agente/
```

El LLM en local necesita `ANTHROPIC_API_KEY` en `.env` (nunca commitearla). Con
`PROVEEDOR_LLM=vertex` usa Vertex AI con `gcloud auth application-default login`. Los tests usan un cliente falso (`tests/fake_llm.py`).

## Variables

| Variable | Uso |
|---|---|
| `DATABASE_URL` | db_agente, rol `agente_app` (secreto `svc-agente-db-url`) |
| `LLM_DATABASE_URL` | db_agente, rol `agente_llm` — **obligatoria en producción** |
| `FUENTES_URL_PLANTILLA` | URL del rol `agente_ro` con `{db}` en lugar del nombre de la base |
| `FUENTE_<VIVIENDA\|PRIVADA\|GASIFERA\|GRALGOB\|DATOS_EXTERNOS>_URL` | override por fuente |
| `SVC_VIVIENDA_INTERNAL_URL` | lookup de rol (ADR-015) |
| `PROVEEDOR_LLM` | `anthropic` (por defecto) o `vertex` |
| `ANTHROPIC_API_KEY` | API key de Anthropic (secreto `svc-agente-anthropic-key`) — **obligatoria con `anthropic`** |
| `MODELO` / `ESFUERZO` | `claude-sonnet-5-5`, `medium` |
| `VERTEX_REGION` / `VERTEX_PROJECT_ID` | solo con `PROVEEDOR_LLM=vertex` (`global`) |
| `CUOTA_DIARIA` | preguntas por usuario por día (100) |

## Puesta en producción (resumen — seguir `/deploy-servicio`)

1. `sql/roles_db_agente.sql` como `postgres` (crea `agente_app`, `agente_llm`, `agente_ro` y `db_agente`).
2. `sql/grants_fuentes.sql` como `postgres` (SELECT por columna en las 5 bases).
3. Secretos: `svc-agente-db-url`, `svc-agente-llm-db-url`, `svc-agente-fuentes-url`, `svc-agente-anthropic-key`.
4. `alembic upgrade head` desde `svc-agente/` (con `cloud-sql-proxy`).
5. SA `svc-agente@` con `roles/cloudsql.client`, acceso a los secretos y `run.invoker` sobre
   `svc-vivienda` (lookup de rol). Solo con Vertex: `roles/aiplatform.user` y cuota de Claude.
6. Trigger `deploy-svc-agente` con `_EXTRA_SECRETS=,LLM_DATABASE_URL=svc-agente-llm-db-url:latest,FUENTES_URL_PLANTILLA=svc-agente-fuentes-url:latest,ANTHROPIC_API_KEY=svc-agente-anthropic-key:latest`
   y `_SVC_VIVIENDA_INTERNAL_URL`.
7. Cloud Scheduler `refrescar-agente` (horario, desfasado de los syncs) → `POST /internal/agente/refrescar`
   con OIDC; su SA necesita `run.invoker` sobre `svc-agente`.
8. Gateway: paths `/api/v1/agente/**` con su `options:` y config nueva; `api-gateway-sa` como
   `run.invoker` sobre `svc-agente`.
