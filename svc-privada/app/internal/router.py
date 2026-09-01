"""Endpoints internos (IAM-only) — NO montados bajo `/api/v1`, sin
`get_current_user`. Protegidos exclusivamente por IAM de Cloud Run
(`roles/run.invoker` otorgado sólo a la SA que los consume). No se declaran en
`infra/gateway/openapi.yaml`. Mismo patrón que `app/internal/router.py` de
svc-vivienda (ADR-015).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.gestiones import service

router = APIRouter(prefix="/internal/privada", tags=["internal"])


@router.get("/rollup-territorial")
async def rollup_territorial(db: AsyncSession = Depends(get_db)):
    """Rollup global por (departamento, localidad) para la federación
    server-side de `resumen_territorial` en svc-vivienda (ADR-016 / E5a).

    Devuelve lo mismo que `GET /api/v1/privada/gestiones/rollup-territorial`
    pero sin exigir un JWT Firebase — el llamador es la SA `svc-vivienda@`, que
    no tiene fila en `portal_usuarios`.
    """
    return await service.rollup_territorial(db)
