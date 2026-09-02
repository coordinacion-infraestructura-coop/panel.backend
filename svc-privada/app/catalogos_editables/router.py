"""Panel de administración de los 3 catálogos editables (ADR-010).

GET: cualquiera con lectura. POST/PATCH/DELETE: `ROLES_TRANSICION` (Admin/Supervisor) —
Operador NO administra catálogos (RE-5).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_LECTURA, ROLES_TRANSICION, AuthUser, require_privada
from app.catalogos_editables import service
from app.catalogos_editables.schemas import AreaIn, CatalogoPatch, CategoriaIn, ProgramaIn
from app.database import get_db

router = APIRouter(tags=["privada-catalogos-editables"])

_LECT = Depends(require_privada(*ROLES_LECTURA))
_ADMIN = Depends(require_privada(*ROLES_TRANSICION))

_NOMBRES = {"categorias", "programas", "areas"}


def _mk(nombre: str, schema_in):
    @router.get(f"/{nombre}", name=f"list_{nombre}")
    async def _list(
        incluir_inactivos: bool = Query(False),
        db: AsyncSession = Depends(get_db),
        _: AuthUser = _LECT,
    ):
        return await service.listar(db, nombre, incluir_inactivos=incluir_inactivos)

    @router.post(f"/{nombre}", status_code=201, name=f"create_{nombre}")
    async def _create(payload: schema_in, db: AsyncSession = Depends(get_db), user: AuthUser = _ADMIN):  # type: ignore[valid-type]
        return await service.crear(db, user, nombre, payload.model_dump(exclude_unset=True))

    @router.patch(f"/{nombre}/{{item_id}}", name=f"update_{nombre}")
    async def _update(item_id: int, payload: CatalogoPatch, db: AsyncSession = Depends(get_db), user: AuthUser = _ADMIN):
        return await service.actualizar(db, user, nombre, item_id, payload.model_dump(exclude_unset=True))

    @router.delete(f"/{nombre}/{{item_id}}", name=f"delete_{nombre}")
    async def _delete(item_id: int, db: AsyncSession = Depends(get_db), user: AuthUser = _ADMIN):
        return await service.eliminar(db, user, nombre, item_id)


_mk("categorias", CategoriaIn)
_mk("programas", ProgramaIn)
_mk("areas", AreaIn)
