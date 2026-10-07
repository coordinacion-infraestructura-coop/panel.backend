from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_ADMIN, ROLES_TRANSICION, AuthUser, require_roles
from app.database import get_db
from app.geo import asignacion, service
from app.geo.schemas import (
    AliasListResponse,
    DeshacerOut,
    DuplicadosResponse,
    PendientesResponse,
    ResolverPendienteIn,
    ResolverPendienteOut,
)

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/duplicados", response_model=DuplicadosResponse)
async def duplicados(
    modulo: Literal["cordon_cuneta", "cordoba_hogar", "mi_lugar"],
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    grupos = await service.detectar_duplicados(db, modulo)
    return {"grupos": grupos}


# Asignación manual de localidades sin resolver — transversal (montado en
# `/api/v1/geo`, sin `/vivienda`: el padrón es de toda la plataforma, ADR-026).
# Spec: docs/files/spec-geo-asignacion-manual-localidades.md
router_transversal = APIRouter(prefix="/geo", tags=["geo"])

_ADMIN = Depends(require_roles(*ROLES_ADMIN))


@router_transversal.get("/pendientes", response_model=PendientesResponse)
async def listar_pendientes(
    estado: Literal["pendiente", "resuelta", "descartada"] = "pendiente",
    origen: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = _ADMIN,
):
    return await asignacion.listar_pendientes(db, estado=estado, origen=origen, limit=limit, offset=offset)


@router_transversal.post("/pendientes/{pendiente_id}/resolver", response_model=ResolverPendienteOut)
async def resolver_pendiente(
    pendiente_id: str,
    data: ResolverPendienteIn,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = _ADMIN,
):
    return await asignacion.resolver_pendiente(db, actor, pendiente_id, data)


@router_transversal.post("/pendientes/{pendiente_id}/descartar")
async def descartar_pendiente(
    pendiente_id: str, db: AsyncSession = Depends(get_db), actor: AuthUser = _ADMIN
):
    await asignacion.descartar_pendiente(db, actor, pendiente_id)
    return {"ok": True}


@router_transversal.post("/pendientes/{pendiente_id}/deshacer", response_model=DeshacerOut)
async def deshacer(
    pendiente_id: str, db: AsyncSession = Depends(get_db), actor: AuthUser = _ADMIN
):
    return await asignacion.deshacer(db, actor, pendiente_id)


@router_transversal.get("/alias", response_model=AliasListResponse)
async def listar_alias(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = _ADMIN,
):
    return await asignacion.listar_alias(db, limit=limit, offset=offset)
