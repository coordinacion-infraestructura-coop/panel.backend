from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, require_roles, require_comunicaciones_write, ROLES_ESCRITURA, ROLES_LECTURA, ROLES_TRANSICION
from app.database import get_db
from app.cordoba_hogar import service
from app.cordoba_hogar.schemas import (
    CordobaHogarFullResponse,
    EstadoCreate,
    EstadoHistorialResponse,
    EstadoResponse,
    EstadoUpdate,
    GeoLocalidadResponse,
    LocalidadCreate,
    LocalidadResponse,
    LocalidadUpdate,
    MontoPorCasaUpdate,
    PedidoCreate,
    PedidoResponse,
    PresupuestoUpdate,
)

router = APIRouter()


@router.get("/cordoba-hogar", response_model=CordobaHogarFullResponse)
async def get_full(
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_full(db)


@router.get("/cordoba-hogar/estados", response_model=list[EstadoResponse])
async def listar_estados(
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_estados(db)


@router.post("/cordoba-hogar/estados", response_model=EstadoResponse, status_code=status.HTTP_201_CREATED)
async def crear_estado(
    data: EstadoCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    return await service.crear_estado(db, data, actor)


@router.patch("/cordoba-hogar/estados/{estado_id}", response_model=EstadoResponse)
async def actualizar_estado(
    estado_id: int,
    data: EstadoUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    return await service.actualizar_estado(db, estado_id, data, actor)


@router.delete("/cordoba-hogar/estados/{estado_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_estado(
    estado_id: int,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    await service.eliminar_estado(db, estado_id, actor)


@router.get("/cordoba-hogar/geo", response_model=list[GeoLocalidadResponse])
async def listar_geo(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_geo_localidades(db)


@router.post("/cordoba-hogar", response_model=LocalidadResponse, status_code=status.HTTP_201_CREATED)
async def crear_localidad(
    data: LocalidadCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.crear_localidad(db, data, actor)


@router.patch("/cordoba-hogar/{localidad_id}", response_model=LocalidadResponse)
async def actualizar_localidad(
    localidad_id: str,
    data: LocalidadUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.actualizar_localidad(db, localidad_id, data, actor)


@router.delete("/cordoba-hogar/{localidad_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_localidad(
    localidad_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    await service.eliminar_localidad(db, localidad_id, actor)


@router.get("/cordoba-hogar/{localidad_id}/historial", response_model=list[EstadoHistorialResponse])
async def get_historial(
    localidad_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_historial(db, localidad_id)


@router.get("/cordoba-hogar/{localidad_id}/pedidos", response_model=list[PedidoResponse])
async def listar_pedidos(
    localidad_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_pedidos(db, localidad_id, actor)


@router.post(
    "/cordoba-hogar/{localidad_id}/pedidos",
    response_model=PedidoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_pedido(
    localidad_id: str,
    data: PedidoCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_comunicaciones_write()),
):
    return await service.crear_pedido(db, localidad_id, data, actor)


@router.delete(
    "/cordoba-hogar/{localidad_id}/pedidos/{pedido_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_pedido(
    localidad_id: str,
    pedido_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    await service.delete_pedido(db, localidad_id, pedido_id, actor)


@router.patch("/cordoba-hogar-config/presupuesto")
async def actualizar_presupuesto(
    data: PresupuestoUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    presupuesto = await service.actualizar_presupuesto(db, data, actor)
    return {"presupuesto": presupuesto}


@router.patch("/cordoba-hogar-config/monto-por-casa")
async def actualizar_monto_por_casa(
    data: MontoPorCasaUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    monto = await service.actualizar_monto_por_casa(db, data, actor)
    return {"monto_por_casa": monto}
