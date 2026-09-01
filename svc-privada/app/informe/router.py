from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_LECTURA, AuthUser, require_privada
from app.database import get_db
from app.informe import service
from app.informe.service import DEFAULT_DESDE

router = APIRouter(prefix="/informe/cooperativas", tags=["privada-informe"])

_LECT = Depends(require_privada(*ROLES_LECTURA))


@router.get("/resumen")
async def resumen(
    fecha_desde: date = Query(default=DEFAULT_DESDE),
    fecha_hasta: date = Query(default_factory=date.today),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.resumen(db, fecha_desde, fecha_hasta)


@router.get("/temporal")
async def temporal(
    fecha_desde: date = Query(default=DEFAULT_DESDE),
    fecha_hasta: date = Query(default_factory=date.today),
    tema: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.temporal(db, fecha_desde, fecha_hasta, tema)


@router.get("/por-departamento")
async def por_departamento(
    fecha_desde: date = Query(default=DEFAULT_DESDE),
    fecha_hasta: date = Query(default_factory=date.today),
    tema: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.por_departamento(db, fecha_desde, fecha_hasta, tema)


@router.get("/puntos")
async def puntos(
    fecha_desde: date = Query(default=DEFAULT_DESDE),
    fecha_hasta: date = Query(default_factory=date.today),
    tema: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.puntos(db, fecha_desde, fecha_hasta, tema)
