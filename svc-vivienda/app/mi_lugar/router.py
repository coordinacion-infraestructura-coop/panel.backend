from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    AuthUser,
    ROLES_ESCRITURA,
    ROLES_LECTURA,
    ROLES_TRANSICION,
    require_comunicaciones_write,
    require_roles,
)
from app.database import get_db
from app.mi_lugar import service
from app.mi_lugar.schemas import (
    ConfigMLOut,
    ConfigMLUpdate,
    EstadoHistorialMLOut,
    EstadoMLCreate,
    EstadoMLOut,
    EstadoMLUpdate,
    PedidoMLCreate,
    PedidoMLOut,
    ProyectoMLCreate,
    ProyectoMLOut,
    ProyectoMLUpdate,
)

router = APIRouter()


# ─── Catálogo de estados ──────────────────────────────────────────────────────

@router.get("/mi-lugar/estados", response_model=list[EstadoMLOut])
async def listar_estados(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_estados_ml(db)


@router.post("/mi-lugar/estados", response_model=EstadoMLOut, status_code=status.HTTP_201_CREATED)
async def crear_estado(
    data: EstadoMLCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    return await service.crear_estado_ml(db, data, actor)


@router.patch("/mi-lugar/estados/{estado_id}", response_model=EstadoMLOut)
async def actualizar_estado(
    estado_id: int,
    data: EstadoMLUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    return await service.actualizar_estado_ml(db, estado_id, data, actor)


@router.delete("/mi-lugar/estados/{estado_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_estado(
    estado_id: int,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    await service.eliminar_estado_ml(db, estado_id, actor)


# ─── Proyectos ────────────────────────────────────────────────────────────────

@router.get("/mi-lugar/proyectos", response_model=list[ProyectoMLOut])
async def listar_proyectos(
    tipo: str | None = Query(None),
    localidad_nombre: str | None = Query(None),
    estado_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_proyectos_ml(db, tipo=tipo, localidad_nombre=localidad_nombre, estado_id=estado_id)


@router.post("/mi-lugar/proyectos", response_model=ProyectoMLOut, status_code=status.HTTP_201_CREATED)
async def crear_proyecto(
    data: ProyectoMLCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.crear_proyecto_ml(db, data, actor)


@router.get("/mi-lugar/proyectos/{proyecto_id}", response_model=ProyectoMLOut)
async def obtener_proyecto(
    proyecto_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.obtener_proyecto_ml(db, proyecto_id)


@router.patch("/mi-lugar/proyectos/{proyecto_id}", response_model=ProyectoMLOut)
async def actualizar_proyecto(
    proyecto_id: str,
    data: ProyectoMLUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.actualizar_proyecto_ml(db, proyecto_id, data, actor)


@router.delete("/mi-lugar/proyectos/{proyecto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_proyecto(
    proyecto_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    await service.eliminar_proyecto_ml(db, proyecto_id, actor)


# ─── Historial ────────────────────────────────────────────────────────────────

@router.get("/mi-lugar/proyectos/{proyecto_id}/historial", response_model=list[EstadoHistorialMLOut])
async def get_historial(
    proyecto_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.get_historial_ml(db, proyecto_id)


# ─── Pedidos / Comunicaciones ─────────────────────────────────────────────────

@router.get("/mi-lugar/proyectos/{proyecto_id}/pedidos", response_model=list[PedidoMLOut])
async def listar_pedidos(
    proyecto_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.listar_pedidos_ml(db, proyecto_id, actor)


@router.post(
    "/mi-lugar/proyectos/{proyecto_id}/pedidos",
    response_model=PedidoMLOut,
    status_code=status.HTTP_201_CREATED,
)
async def crear_pedido(
    proyecto_id: str,
    data: PedidoMLCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_comunicaciones_write()),
):
    return await service.crear_pedido_ml(db, proyecto_id, data, actor)


@router.delete(
    "/mi-lugar/proyectos/{proyecto_id}/pedidos/{pedido_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def eliminar_pedido(
    proyecto_id: str,
    pedido_id: str,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    await service.eliminar_pedido_ml(db, proyecto_id, pedido_id, actor)


# ─── Configuración ────────────────────────────────────────────────────────────

@router.get("/mi-lugar-config", response_model=ConfigMLOut)
async def obtener_config(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA)),
):
    return await service.obtener_config_ml(db)


@router.patch("/mi-lugar-config", response_model=ConfigMLOut)
async def actualizar_config(
    data: ConfigMLUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA)),
):
    return await service.actualizar_config_ml(db, data, actor)
