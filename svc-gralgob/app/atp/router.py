"""Panel preliminar de solo lectura sobre los datos ya sincronizados
(spec-sync-atp-compromiso-gobernador.md §12) — excepción documentada y
autorizada explícitamente por el usuario a la regla de CLAUDE.md que exige
spec-svc-gralgob.md `approved` para cualquier otro endpoint `/api/v1/gralgob/**`.

Solo lectura: sin POST/PATCH/DELETE, sin lógica de negocio nueva — cada
respuesta refleja 1:1 lo que ya está en atp_compromisos/atp_cronograma_pagos
(salvo `total_pagado`, un `SUM` simple, no una regla de negocio nueva).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp import sync as atp_sync
from app.atp.schemas import CompromisosListResponse, SyncStatusResponse
from app.auth import ROLES_LECTURA, AuthUser, require_gralgob
from app.database import get_db

router = APIRouter(tags=["gralgob-atp"])

_LECT = Depends(require_gralgob(*ROLES_LECTURA))


@router.get("/compromisos", response_model=CompromisosListResponse)
async def listar_compromisos(
    limit: int = Query(1200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    items, total = await atp_sync.listar_compromisos(db, limit=limit, offset=offset)
    return CompromisosListResponse(items=items, total=total)


@router.get("/sync-estado", response_model=SyncStatusResponse | None)
async def sync_estado(db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await atp_sync.get_last_sync_status(db)
