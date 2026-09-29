"""Endpoints internos, no expuestos por API Gateway.

Estos paths NO se declaran en infra/gateway/openapi.yaml a propósito — quedan
invisibles para el Gateway. El único control de acceso, cuando esto se
despliegue de verdad, es IAM a nivel de Cloud Run (--no-allow-unauthenticated):
solo principals con `roles/run.invoker` sobre el servicio pueden invocarlos
(Cloud Scheduler para el sync mensual, svc-vivienda para el rollup). No usan
`Depends(get_current_user)` porque no hay JWT de Firebase en este flujo y
svc-datos-externos no tiene ningún endpoint de negocio ni panel propio (v1).

Ver spec: docs/files/spec-resumen-territorial-tablero-v2.md §2.5
"""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import rollup
from app.database import get_db
from app.transferencias import sync as transferencias_sync
from app.transferencias.schemas import SyncResultResponse, SyncStatusResponse

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/datos-externos/rollup-territorial")
async def rollup_territorial(db: AsyncSession = Depends(get_db)):
    """Consumido por resumen_territorial de svc-vivienda (ADR-025). Solo la
    SA de svc-vivienda tiene roles/run.invoker sobre este servicio."""
    return await rollup.rollup_territorial(db)


@router.post("/datos-externos/transferencias/sync", response_model=SyncResultResponse)
async def sync_transferencias(
    tipo: str,
    periodo: date,
    triggered_by: str = "cloud-scheduler",
    db: AsyncSession = Depends(get_db),
):
    """Disparado por Cloud Scheduler (mensual, día 5) o manualmente. `periodo`
    es el primer día del mes a sincronizar (ej. 2026-07-01)."""
    if tipo not in ("municipio", "comuna"):
        raise HTTPException(status_code=422, detail={"code": "TIPO_INVALIDO", "message": "tipo debe ser 'municipio' o 'comuna'"})
    try:
        return await transferencias_sync.sync_periodo_automatico(db, tipo, periodo, disparado_por=triggered_by)
    except transferencias_sync.ExtraccionFallida as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "TRANSFERENCIAS_SYNC_FALLIDO", "message": str(exc)},
        )


@router.post("/datos-externos/transferencias/cargar-manual", response_model=SyncResultResponse)
async def cargar_manual(
    tipo: str = Form(...),
    periodo: date = Form(...),
    disparado_por: str = Form("manual"),
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Modo de respaldo (spec §2.3 paso 7) para cuando el scraping automático
    falla — el sitio bloquea clientes automatizados y puede volver a
    bloquear pese al user-agent de navegador. Reusa el mismo parser."""
    if tipo not in ("municipio", "comuna"):
        raise HTTPException(status_code=422, detail={"code": "TIPO_INVALIDO", "message": "tipo debe ser 'municipio' o 'comuna'"})
    pdf_bytes = await archivo.read()
    try:
        return await transferencias_sync.sync_desde_pdf(db, pdf_bytes, tipo, periodo, disparado_por=disparado_por)
    except transferencias_sync.ExtraccionFallida as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "TRANSFERENCIAS_EXTRACCION_FALLIDA", "message": str(exc)},
        )


@router.get("/datos-externos/transferencias/sync-estado", response_model=SyncStatusResponse | None)
async def estado_sync_transferencias(tipo: str | None = None, db: AsyncSession = Depends(get_db)):
    log = await transferencias_sync.get_last_sync_status(db, tipo=tipo)
    return SyncStatusResponse.model_validate(log) if log else None
