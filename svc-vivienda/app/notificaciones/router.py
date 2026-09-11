from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_LECTURA, AuthUser, require_roles
from app.database import get_db
from app.notificaciones import service
from app.notificaciones.schemas import NotificacionesListResponse

# Tupla local — todos los roles reales del portal ven sus notificaciones.
# `Autoridad`/`TecnicoDGV` NO se agregan a las constantes de `app.auth` (misma
# convención que resumen_territorial / spec-checklist-tecnico-dgv.md §8).
ROLES_NOTIF = ROLES_LECTURA + ("Autoridad", "TecnicoDGV")

router = APIRouter(tags=["notificaciones"])

_LECT = Depends(require_roles(*ROLES_NOTIF))


@router.get("/notificaciones", response_model=NotificacionesListResponse)
async def listar_notificaciones(
    solo_no_leidas: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = _LECT,
):
    """Feed de notificaciones visibles para el usuario, ya con su estado leído/no leído."""
    return await service.listar(
        db, actor, solo_no_leidas=solo_no_leidas, limit=limit, offset=offset
    )


@router.get("/notificaciones/no-leidas/contar")
async def contar_no_leidas(db: AsyncSession = Depends(get_db), actor: AuthUser = _LECT):
    """Conteo de no leídas — lo consume el badge de la campana (poll cada 60 s)."""
    return {"no_leidas": await service.contar_no_leidas(db, actor)}


@router.post("/notificaciones/marcar-todas-leidas")
async def marcar_todas_leidas(db: AsyncSession = Depends(get_db), actor: AuthUser = _LECT):
    marcadas = await service.marcar_todas_leidas(db, actor)
    return {"ok": True, "marcadas": marcadas}


@router.post("/notificaciones/{notif_id}/marcar-leida")
async def marcar_leida(
    notif_id: str, db: AsyncSession = Depends(get_db), actor: AuthUser = _LECT
):
    await service.marcar_leida(db, actor, notif_id)
    return {"ok": True}
