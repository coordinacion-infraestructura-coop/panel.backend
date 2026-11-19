"""Planificación de programas por localidad — `/api/v1/privada/planificacion/**`.

Acceso (spec §3): Privada + Admin. **Autoridad queda afuera a propósito** aunque esté en el
`ROLES_LECTURA` compartido, por eso las tuplas son locales. Configuración (programas,
prioridades, estados, columnas): Supervisor/Admin; borrar un programa: sólo Admin.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_ELIMINACION, ROLES_ESCRITURA, ROLES_TRANSICION, AuthUser, require_privada
from app.database import get_db
from app.planificacion import service
from app.planificacion.schemas import (
    ColumnaIn,
    ColumnaOut,
    ColumnaPatch,
    EstadoIn,
    EstadoOut,
    EstadoPatch,
    HistorialOut,
    LocalidadesOut,
    LocalidadPatch,
    PrioridadIn,
    PrioridadOut,
    PrioridadPatch,
    ProgramaIn,
    ProgramaOut,
    ProgramaPatch,
)

ROLES_LECTURA_PLAN = ("Admin", "Supervisor", "Operador", "Consulta")

router = APIRouter(prefix="/planificacion", tags=["privada-planificacion"])

_LECT = Depends(require_privada(*ROLES_LECTURA_PLAN))
_ESCR = Depends(require_privada(*ROLES_ESCRITURA))
_CONF = Depends(require_privada(*ROLES_TRANSICION))
_ELIM = Depends(require_privada(*ROLES_ELIMINACION))


# --- programas ---------------------------------------------------------------------------

@router.get("/programas", response_model=list[ProgramaOut])
async def listar_programas(incluir_inactivos: bool = Query(False), db: AsyncSession = Depends(get_db), _: AuthUser = _LECT):
    return await service.listar_programas(db, incluir_inactivos=incluir_inactivos)


@router.post("/programas", response_model=ProgramaOut, status_code=201)
async def crear_programa(payload: ProgramaIn, db: AsyncSession = Depends(get_db), user: AuthUser = _CONF):
    return await service.crear_programa(db, user, payload.model_dump())


@router.patch("/programas/{programa_id}", response_model=ProgramaOut)
async def actualizar_programa(programa_id: int, payload: ProgramaPatch, db: AsyncSession = Depends(get_db), user: AuthUser = _CONF):
    return await service.actualizar_programa(db, user, programa_id, payload.model_dump(exclude_unset=True))


@router.delete("/programas/{programa_id}")
async def eliminar_programa(programa_id: int, db: AsyncSession = Depends(get_db), user: AuthUser = _ELIM):
    return await service.eliminar_programa(db, user, programa_id)


# --- catálogos por programa --------------------------------------------------------------

def _mk(nombre: str, schema_in, schema_patch, schema_out) -> None:
    base = f"/programas/{{programa_id}}/{nombre}"

    @router.get(base, response_model=list[schema_out], name=f"listar_{nombre}")
    async def _list(
        programa_id: int,
        incluir_eliminados: bool = Query(False),
        db: AsyncSession = Depends(get_db),
        _: AuthUser = _LECT,
    ):
        return await service.listar_catalogo(db, programa_id, nombre, incluir_eliminados=incluir_eliminados)

    @router.post(base, response_model=schema_out, status_code=201, name=f"crear_{nombre}")
    async def _create(programa_id: int, payload: schema_in, db: AsyncSession = Depends(get_db), user: AuthUser = _CONF):  # type: ignore[valid-type]
        return await service.crear_item(db, user, programa_id, nombre, payload.model_dump())  # type: ignore[attr-defined]

    @router.patch(f"{base}/{{item_id}}", response_model=schema_out, name=f"actualizar_{nombre}")
    async def _update(programa_id: int, item_id: int, payload: schema_patch, db: AsyncSession = Depends(get_db), user: AuthUser = _CONF):  # type: ignore[valid-type]
        return await service.actualizar_item(db, user, programa_id, nombre, item_id, payload.model_dump(exclude_unset=True))  # type: ignore[attr-defined]

    @router.delete(f"{base}/{{item_id}}", name=f"eliminar_{nombre}")
    async def _delete(programa_id: int, item_id: int, db: AsyncSession = Depends(get_db), user: AuthUser = _CONF):
        return await service.eliminar_item(db, user, programa_id, nombre, item_id)


_mk("estados", EstadoIn, EstadoPatch, EstadoOut)
_mk("prioridades", PrioridadIn, PrioridadPatch, PrioridadOut)
_mk("columnas", ColumnaIn, ColumnaPatch, ColumnaOut)


# --- planilla ----------------------------------------------------------------------------

@router.get("/programas/{programa_id}/localidades", response_model=LocalidadesOut)
async def listar_localidades(
    programa_id: int,
    departamento: str | None = Query(None),
    limit: int = Query(service.LIMIT_MAX, ge=1, le=service.LIMIT_MAX),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.listar_localidades(db, programa_id, departamento=departamento, limit=limit, offset=offset)


@router.patch("/programas/{programa_id}/localidades/{id_geo}")
async def actualizar_localidad(
    programa_id: int, id_geo: str, payload: LocalidadPatch, db: AsyncSession = Depends(get_db), user: AuthUser = _ESCR
):
    return await service.actualizar_localidad(db, user, programa_id, id_geo, payload.model_dump(exclude_unset=True))


@router.get("/programas/{programa_id}/localidades/{id_geo}/historial", response_model=list[HistorialOut])
async def historial(
    programa_id: int,
    id_geo: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AuthUser = _LECT,
):
    return await service.historial(db, programa_id, id_geo, limit=limit, offset=offset)
