from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, require_roles, ROLES_ESCRITURA, ROLES_LECTURA, ROLES_TRANSICION
from app.cordon_cuneta import service
from app.cordon_cuneta.schemas import (
    CordonCunetaFullResponse,
    EstadoCreate,
    EstadoHistorialResponse,
    EstadoResponse,
    EstadoUpdate,
    GeoLocalidadResponse,
    MunicipioCreate,
    MunicipioResponse,
    MunicipioUpdate,
    PedidoCreate,
    PedidoResponse,
    PresupuestoUpdate,
)
from app.database import get_db

router = APIRouter()


@router.get("/cordon-cuneta", response_model=CordonCunetaFullResponse)
async def get_panel(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_full(db)


@router.get("/cordon-cuneta/estados", response_model=list[EstadoResponse])
async def listar_estados(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_estados(db)


@router.post("/cordon-cuneta/estados", response_model=EstadoResponse, status_code=status.HTTP_201_CREATED)
async def crear_estado(
    data: EstadoCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    return await service.crear_estado(db, data, actor)


@router.patch("/cordon-cuneta/estados/{estado_id}", response_model=EstadoResponse)
async def actualizar_estado(
    estado_id: int,
    data: EstadoUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    return await service.actualizar_estado(db, estado_id, data, actor)


@router.delete("/cordon-cuneta/estados/{estado_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_estado(
    estado_id: int,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    await service.eliminar_estado(db, estado_id, actor)


@router.get("/cordon-cuneta/geo", response_model=list[GeoLocalidadResponse])
async def listar_geo(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_geo_localidades(db)


@router.post("/cordon-cuneta", response_model=MunicipioResponse, status_code=status.HTTP_201_CREATED)
async def crear_municipio(
    data: MunicipioCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.crear_municipio(db, data, actor)


@router.patch("/cordon-cuneta/{municipio_id}", response_model=MunicipioResponse)
async def actualizar_municipio(
    municipio_id: str,
    data: MunicipioUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.actualizar_municipio(db, municipio_id, data, actor)


@router.delete("/cordon-cuneta/{municipio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_municipio(
    municipio_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    await service.eliminar_municipio(db, municipio_id, actor)


@router.get("/cordon-cuneta/{municipio_id}/historial", response_model=list[EstadoHistorialResponse])
async def get_historial(
    municipio_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_historial(db, municipio_id)


@router.get("/cordon-cuneta/{municipio_id}/pedidos", response_model=list[PedidoResponse])
async def listar_pedidos(
    municipio_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_pedidos(db, municipio_id)


@router.post("/cordon-cuneta/{municipio_id}/pedidos", response_model=PedidoResponse, status_code=201)
async def crear_pedido(
    municipio_id: str,
    data: PedidoCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.crear_pedido(db, municipio_id, data, actor)


@router.delete("/cordon-cuneta/{municipio_id}/pedidos/{pedido_id}", status_code=204)
async def eliminar_pedido(
    municipio_id: str,
    pedido_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    await service.delete_pedido(db, municipio_id, pedido_id, actor)


@router.patch("/cordon-cuneta-config/presupuesto")
async def actualizar_presupuesto(
    data: PresupuestoUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    presupuesto = await service.actualizar_presupuesto(db, data, actor)
    return {"presupuesto": presupuesto}
