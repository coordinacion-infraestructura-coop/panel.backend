from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_LECTURA, AuthUser, require_privada
from app.catalogos import service
from app.database import get_db

router = APIRouter(prefix="/catalogos", tags=["privada-catalogos"])

_LECT = Depends(require_privada(*ROLES_LECTURA))


@router.get("/departamentos")
async def departamentos(db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await service.departamentos(db)


@router.get("/localidades")
async def localidades(
    departamento: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.localidades(db, departamento)


@router.get("/geo")
async def geo(
    departamento: str = Query(..., min_length=1),
    localidad: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.geo(db, departamento, localidad)


@router.get("/{nombre}")
async def catalogo(nombre: str, db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await service.listar(db, nombre)
