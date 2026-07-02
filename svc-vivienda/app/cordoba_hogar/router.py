from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, get_current_user, require_roles
from app.database import get_db
from app.cordoba_hogar import service
from app.cordoba_hogar.schemas import (
    CordobaHogarFullResponse,
    EstadoResponse,
    LocalidadResponse,
    LocalidadUpdate,
    PedidoCreate,
    PedidoResponse,
    PresupuestoUpdate,
)

ROLES_LECTURA = ("Admin", "Supervisor", "Operador", "Consulta")
ROLES_ESCRITURA = ("Admin", "Supervisor", "Operador")

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


@router.patch("/cordoba-hogar/{localidad_id}", response_model=LocalidadResponse)
async def actualizar_localidad(
    localidad_id: str,
    data: LocalidadUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.actualizar_localidad(db, localidad_id, data, actor)


@router.get("/cordoba-hogar/{localidad_id}/pedidos", response_model=list[PedidoResponse])
async def listar_pedidos(
    localidad_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_pedidos(db, localidad_id)


@router.post(
    "/cordoba-hogar/{localidad_id}/pedidos",
    response_model=PedidoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_pedido(
    localidad_id: str,
    data: PedidoCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
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
