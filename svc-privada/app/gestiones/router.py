from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    ROLES_ESCRITURA,
    ROLES_LECTURA,
    ROLES_TRANSICION,
    AuthUser,
    require_privada,
)
from app.database import get_db
from app.gestiones import service
from app.gestiones.schemas import CambioEstado, GestionCreate, GestionUpdate, LocalidadInfoUpsert

router = APIRouter(tags=["privada-gestiones"])

_LECT = Depends(require_privada(*ROLES_LECTURA))
_ESCR = Depends(require_privada(*ROLES_ESCRITURA))
_TRAN = Depends(require_privada(*ROLES_TRANSICION))


# ── Listado / resumen territorial ──────────────────────────────────────────

@router.get("/gestiones")
@router.get("/gestiones/")
async def list_gestiones(
    estado: str | None = None,
    ministerio: str | None = None,
    categoria: str | None = None,
    departamento: str | None = None,
    localidad: str | None = None,
    q: str | None = None,
    tipo_gestion: str | None = None,
    canal_origen: str | None = None,
    ok_gobernador: str | None = Query(None, pattern="^(SI|NO|PENDIENTE)$"),
    ok_ministro: str | None = Query(None, pattern="^(SI|NO|PENDIENTE)$"),
    categoria_id: int | None = Query(None, description="filtra por priv_categorias.id (Campo de Trabajo)"),
    programa_id: int | None = Query(None),
    area_id: int | None = Query(None),
    sort: str | None = Query(None, description="fecha_ingreso|fecha_estado|dias_transcurridos|estado|urgencia|departamento|localidad|nro_expediente|costo_estimado|ministerio|categoria|tipo_gestion|canal_origen"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.listar_gestiones(
        db, estado=estado, ministerio=ministerio, categoria=categoria,
        departamento=departamento, localidad=localidad, q=q,
        tipo_gestion=tipo_gestion, canal_origen=canal_origen,
        ok_gobernador=ok_gobernador, ok_ministro=ok_ministro,
        categoria_id=categoria_id, programa_id=programa_id, area_id=area_id,
        sort=sort, sort_dir=sort_dir, limit=limit, offset=offset,
    )


@router.get("/gestiones/resumen-territorial")
async def resumen_territorial(
    departamento: str = Query(..., min_length=1),
    localidad: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.resumen_territorial(db, departamento, localidad)


@router.get("/gestiones/rollup-territorial")
async def rollup_territorial(db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await service.rollup_territorial(db)


# ── Detalle / eventos ─────────────────────────────────────────────────────

@router.get("/gestiones/{id_gestion}")
async def get_gestion(id_gestion: str, db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await service.get_gestion(db, id_gestion)


@router.get("/gestiones/{id_gestion}/eventos")
async def list_eventos(id_gestion: str, db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await service.listar_eventos(db, id_gestion)


# ── Escrituras ───────────────────────────────────────────────────────────

@router.post("/gestiones", status_code=201)
@router.post("/gestiones/", status_code=201)
async def create_gestion(
    payload: GestionCreate, db: AsyncSession = Depends(get_db), user: AuthUser = _ESCR
):
    return await service.crear_gestion(db, user, payload)


@router.post("/gestiones/{id_gestion}/cambiar-estado")
async def cambiar_estado(
    id_gestion: str, payload: CambioEstado, db: AsyncSession = Depends(get_db), user: AuthUser = _ESCR
):
    return await service.cambiar_estado(db, user, id_gestion, payload)


@router.patch("/gestiones/{id_gestion}")
async def patch_gestion(
    id_gestion: str, payload: GestionUpdate, db: AsyncSession = Depends(get_db), user: AuthUser = _ESCR
):
    return await service.patch_gestion(db, user, id_gestion, payload)


@router.delete("/gestiones/{id_gestion}")
async def delete_gestion(id_gestion: str, db: AsyncSession = Depends(get_db), user: AuthUser = _TRAN):
    return await service.eliminar_gestion(db, user, id_gestion)


# ── Datos territoriales ──────────────────────────────────────────────────

@router.get("/localidades-info/all")
async def list_localidades_info(db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await service.listar_localidades_info(db)


@router.get("/localidades-info")
async def get_localidad_info(
    departamento: str = Query(..., min_length=1),
    localidad: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.get_localidad_info(db, departamento, localidad)


@router.put("/localidades-info")
async def put_localidad_info(
    payload: LocalidadInfoUpsert, db: AsyncSession = Depends(get_db), user: AuthUser = _ESCR
):
    return await service.put_localidad_info(db, user, payload)


@router.get("/departamentos-info")
async def get_departamento_info(
    departamento: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.get_departamento_info(db, departamento)
