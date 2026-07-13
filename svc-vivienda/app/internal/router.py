"""Endpoints internos, no expuestos por API Gateway.

Estos paths NO se declaran en infra/gateway/openapi.yaml a propósito — quedan
invisibles para el Gateway. El único control de acceso es IAM a nivel de
Cloud Run (--no-allow-unauthenticated): solo principals con `roles/run.invoker`
sobre el servicio pueden invocarlos. No usan `Depends(get_current_user)` porque
no hay JWT de Firebase en este flujo (Cloud Scheduler → OIDC → Cloud Run IAM).

Ver spec: docs/files/spec-sync-cc-checklist-tecnico.md
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordon_cuneta import checklist_sync
from app.cordon_cuneta.checklist_schemas import SyncResultResponse
from app.database import get_db

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/sync/cordon-cuneta-checklist", response_model=SyncResultResponse)
async def sync_cordon_cuneta_checklist(
    triggered_by: str = "cloud-scheduler",
    db: AsyncSession = Depends(get_db),
):
    try:
        return await checklist_sync.sync_from_sheet(db, triggered_by=triggered_by)
    except checklist_sync.SheetReadError as exc:
        # 502: la falla es de la fuente externa (Sheet/Sheets API), no del servicio.
        # Cloud Scheduler marca esta ejecución como fallida — dispara la alerta
        # de Cloud Monitoring configurada sobre este endpoint.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "SHEET_SYNC_FALLIDO", "message": str(exc)},
        )
