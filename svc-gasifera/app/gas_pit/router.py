"""Panel preliminar de solo lectura sobre los datos ya sincronizados
(spec-sync-gasifera-pit.md §12) — excepción documentada y autorizada
explícitamente por el usuario a la regla de CLAUDE.md que exige
spec-svc-gasifera.md `approved` para cualquier otro endpoint `/api/v1/gasifera/**`.

Solo lectura: sin POST/PATCH/DELETE, sin lógica de negocio nueva — cada
respuesta refleja 1:1 lo que ya está en gas_pit_obras/gas_pit_acciones_territorio.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_LECTURA, AuthUser, require_gasifera
from app.database import get_db
from app.gas_pit import sync as gas_pit_sync
from app.gas_pit.schemas import (
    AccionesTerritorioListResponse,
    ObrasGasListResponse,
    SyncStatusResponse,
)

router = APIRouter(tags=["gasifera-pit"])

_LECT = Depends(require_gasifera(*ROLES_LECTURA))


@router.get("/obras", response_model=ObrasGasListResponse)
async def listar_obras(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    items, total = await gas_pit_sync.listar_obras(db, limit=limit, offset=offset)
    return ObrasGasListResponse(items=items, total=total)


@router.get("/acciones-territorio", response_model=AccionesTerritorioListResponse)
async def listar_acciones_territorio(
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    items, total = await gas_pit_sync.listar_acciones_territorio(db, limit=limit, offset=offset)
    return AccionesTerritorioListResponse(items=items, total=total)


@router.get("/sync-estado", response_model=SyncStatusResponse | None)
async def sync_estado(db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await gas_pit_sync.get_last_sync_status(db)
