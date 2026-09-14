"""Endpoints internos (IAM-only) — NO montados bajo `/api/v1`, sin
`get_current_user`. Protegidos exclusivamente por IAM de Cloud Run
(`roles/run.invoker` otorgado sólo a la SA que los consume). No se declaran en
`infra/gateway/openapi.yaml`. Mismo patrón que `app/internal/router.py` de
svc-vivienda (ADR-015).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.database import get_db
from app.gestiones import service, vivienda_sync
from app.internal.schemas import GestionSyncFromVivienda, GestionSyncResult

router = APIRouter(prefix="/internal/privada", tags=["internal"])

# Actor sintético para las llamadas server-to-server de svc-vivienda (no hay JWT en
# este flujo) — mismo patrón que `_SCHEDULER_ACTOR` en el internal router de svc-vivienda.
_VIVIENDA_ACTOR = AuthUser(uid="svc-vivienda", email="svc-vivienda@system", role="system", secretarias=[])


@router.get("/rollup-territorial")
async def rollup_territorial(db: AsyncSession = Depends(get_db)):
    """Rollup global por (departamento, localidad) para la federación
    server-side de `resumen_territorial` en svc-vivienda (ADR-016 / E5a).

    Devuelve lo mismo que `GET /api/v1/privada/gestiones/rollup-territorial`
    pero sin exigir un JWT Firebase — el llamador es la SA `svc-vivienda@`, que
    no tiene fila en `portal_usuarios`.
    """
    return await service.rollup_territorial(db)


@router.post("/gestiones/sync", response_model=GestionSyncResult)
async def sync_gestion_desde_vivienda(
    payload: GestionSyncFromVivienda, db: AsyncSession = Depends(get_db)
):
    """Crea o vincula/sincroniza una gestión a partir de un caso de Vivienda
    (Cordón Cuneta / Córdoba Hogar / Mi Lugar) — ADR-020,
    `docs/files/spec-vinculacion-vivienda-privada.md`.

    Idempotente vía `id_legacy` determinístico. Resultados de negocio
    (`PENDING_REVIEW`, geo inválida) viajan en el body con 200, no como error
    HTTP — sólo un payload inválido (422) o una excepción no prevista (500)
    generan un status distinto de 200.
    """
    return await vivienda_sync.sync_gestion_from_vivienda(db, _VIVIENDA_ACTOR, payload)
