from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, ROLES_ADMIN, ROLES_ESCRITURA, ROLES_LECTURA, require_roles
from app.checklist_tecnico import service
from app.checklist_tecnico.catalog import Programa, TipoHito
from app.checklist_tecnico.schemas import (
    CatalogoEstadoExpedienteCreate,
    CatalogoEstadoExpedienteResponse,
    CatalogoEstadoExpedienteUpdate,
    CatalogoReparticionCreate,
    CatalogoReparticionResponse,
    CatalogoReparticionUpdate,
    CatalogosResponse,
    ChecklistItemUpdate,
    ChecklistTecnicoResponse,
    ChecklistTecnicoUpdate,
    HitoUpdate,
)
from app.database import get_db

# Constantes LOCALES a este módulo — NO se agregan a app/auth.py ni se tocan los routers
# de cordon_cuneta/cordoba_hogar/mi_lugar. Si "TecnicoDGV" se agregara a las constantes
# compartidas de app.auth, se filtraría automáticamente a esos 3 paneles completos, que es
# exactamente lo que el área NO quiere (ver spec-checklist-tecnico-dgv.md §8).
ROLES_LECTURA_CHECKLIST = ROLES_LECTURA + ("TecnicoDGV",)
ROLES_ESCRITURA_CHECKLIST = ROLES_ESCRITURA + ("TecnicoDGV",)

router = APIRouter()


@router.get("/checklist-tecnico/catalogos", response_model=CatalogosResponse)
async def get_catalogos(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA_CHECKLIST)),
):
    return await service.get_catalogos(db)


@router.get("/checklist-tecnico/{programa}/{entidad_id}", response_model=ChecklistTecnicoResponse)
async def get_checklist(
    programa: Programa,
    entidad_id: str,
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA_CHECKLIST)),
):
    return await service.get_checklist(db, programa, entidad_id)


@router.patch("/checklist-tecnico/{programa}/{entidad_id}", response_model=ChecklistTecnicoResponse)
async def actualizar_checklist(
    programa: Programa,
    entidad_id: str,
    data: ChecklistTecnicoUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA_CHECKLIST)),
):
    return await service.actualizar_checklist(db, programa, entidad_id, data, actor)


@router.patch("/checklist-tecnico/{programa}/{entidad_id}/items/{item_num}", response_model=ChecklistTecnicoResponse)
async def actualizar_item(
    programa: Programa,
    entidad_id: str,
    item_num: int,
    data: ChecklistItemUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA_CHECKLIST)),
):
    return await service.actualizar_item(db, programa, entidad_id, item_num, data, actor)


@router.patch("/checklist-tecnico/{programa}/{entidad_id}/hitos/{tipo}", response_model=ChecklistTecnicoResponse)
async def actualizar_hito(
    programa: Programa,
    entidad_id: str,
    tipo: TipoHito,
    data: HitoUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA_CHECKLIST)),
):
    return await service.actualizar_hito(db, programa, entidad_id, tipo, data, actor)


# ── Admin de catálogos (sin TecnicoDGV — coincide con la respuesta del área) ──────────

@router.post(
    "/checklist-tecnico/admin/estado-expediente",
    response_model=CatalogoEstadoExpedienteResponse,
    status_code=201,
)
async def crear_estado_expediente(
    data: CatalogoEstadoExpedienteCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ADMIN)),
):
    return await service.crear_estado_expediente(db, data, actor)


@router.patch("/checklist-tecnico/admin/estado-expediente/{estado_id}", response_model=CatalogoEstadoExpedienteResponse)
async def actualizar_estado_expediente(
    estado_id: int,
    data: CatalogoEstadoExpedienteUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ADMIN)),
):
    return await service.actualizar_estado_expediente(db, estado_id, data, actor)


@router.post("/checklist-tecnico/admin/reparticion", response_model=CatalogoReparticionResponse, status_code=201)
async def crear_reparticion(
    data: CatalogoReparticionCreate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ADMIN)),
):
    return await service.crear_reparticion(db, data, actor)


@router.patch("/checklist-tecnico/admin/reparticion/{reparticion_id}", response_model=CatalogoReparticionResponse)
async def actualizar_reparticion(
    reparticion_id: int,
    data: CatalogoReparticionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ADMIN)),
):
    return await service.actualizar_reparticion(db, reparticion_id, data, actor)
