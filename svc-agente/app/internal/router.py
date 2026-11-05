"""Endpoints IAM-only (sin /api/v1, sin get_current_user, fuera del gateway). Protegidos sólo
por Cloud Run IAM: `roles/run.invoker` para la SA de Cloud Scheduler."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.etl.carga import refrescar

router = APIRouter(prefix="/internal/agente", tags=["internal"])


@router.post("/refrescar")
async def refrescar_capa_semantica(db: AsyncSession = Depends(get_db)):
    """Recarga `ag_*` desde las cinco bases (spec §2.2). Cloud Scheduler, cada hora."""
    estado = await refrescar(db)
    return {"fuentes": estado}
