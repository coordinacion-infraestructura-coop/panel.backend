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

from app.auth import AuthUser
from app.cordon_cuneta import checklist_sync
from app.cordon_cuneta.checklist_schemas import SyncResultResponse
from app.database import get_db
from app.portal.repository import get_portal_user
from app.resumen_territorial import service as resumen_service

router = APIRouter(prefix="/internal", tags=["internal"])

# Actor sintético para las corridas disparadas por Cloud Scheduler (no hay JWT en este flujo)
_SCHEDULER_ACTOR = AuthUser(uid="cloud-scheduler", email="cloud-scheduler", role="system", secretarias=[])


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


@router.get("/portal/usuarios/{email}")
async def portal_usuario_por_email(email: str, db: AsyncSession = Depends(get_db)):
    """Lookup de rol + secretarías de un usuario del portal, para consumo cross-service
    (ADR-015). Lo llama `svc-privada` (SA con `roles/run.invoker` sobre este servicio) para
    resolver la auth sin conectarse a `db_vivienda`. Sólo usuarios activos — 404 si no existe
    o está inactivo (el caller degrada a rol `invitado`, igual que `app/auth.py`)."""
    usuario = await get_portal_user(db, email)
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USUARIO_NO_REGISTRADO", "message": "Usuario no encontrado o inactivo"},
        )
    return {
        "email": usuario.email,
        "rol": usuario.rol,
        "nombre": usuario.nombre,
        "secretarias": [s.secretaria for s in usuario.secretarias],
        "activo": usuario.activo,
    }


@router.post("/resumen-territorial/actualizar")
async def actualizar_resumen_territorial(db: AsyncSession = Depends(get_db)):
    """Recalcula el snapshot del Resumen Territorial. Lo dispara Cloud Scheduler
    (OIDC → Cloud Run IAM). El fetch de Privada es tolerante a fallos dentro del
    cómputo; un 502 acá significa que falló el cálculo de Vivienda o el guardado."""
    try:
        snapshot = await resumen_service.actualizar_resumen(db, _SCHEDULER_ACTOR)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "RESUMEN_TERRITORIAL_FALLIDO", "message": str(exc)},
        )
    return {
        "computed_at": snapshot.computed_at,
        "duracion_ms": snapshot.duracion_ms,
        "total_localidades": snapshot.payload.get("total_localidades"),
        "generado_para_areas": snapshot.payload.get("generado_para_areas"),
    }
