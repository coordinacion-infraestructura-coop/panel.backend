"""Endpoints internos, no expuestos por API Gateway.

Estos paths NO se declaran en infra/gateway/openapi.yaml a propósito — quedan
invisibles para el Gateway. El único control de acceso, cuando esto se
despliegue de verdad, es IAM a nivel de Cloud Run (--no-allow-unauthenticated):
solo principals con `roles/run.invoker` sobre el servicio pueden invocarlos.
No usan `Depends(get_current_user)` porque no hay JWT de Firebase en este flujo
(Cloud Scheduler -> OIDC -> Cloud Run IAM), y svc-gralgob en esta fase (solo
sync) no tiene ningún endpoint de negocio ni integración con portal_usuarios.

Ver spec: docs/files/spec-sync-atp-compromiso-gobernador.md
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp import sync as atp_sync
from app.atp.schemas import SyncResultResponse, SyncStatusResponse
from app.database import get_db

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/sync/atp-compromiso-gobernador", response_model=SyncResultResponse)
async def sync_atp_compromiso_gobernador(
    triggered_by: str = "cloud-scheduler",
    db: AsyncSession = Depends(get_db),
):
    try:
        return await atp_sync.sync_from_sheet(db, triggered_by=triggered_by)
    except atp_sync.SheetReadError as exc:
        # 502: la falla es de la fuente externa (Sheet/Sheets API), no del servicio.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "SHEET_SYNC_FALLIDO", "message": str(exc)},
        )


@router.get("/sync/atp-compromiso-gobernador/estado", response_model=SyncStatusResponse | None)
async def estado_sync_atp_compromiso_gobernador(db: AsyncSession = Depends(get_db)):
    return await atp_sync.get_last_sync_status(db)
