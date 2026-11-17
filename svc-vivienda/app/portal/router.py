from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser, get_current_user
from app.database import get_db
from app.portal import repository
from app.portal.schemas import (
    AREAS_POR_SECRETARIA,
    ROLES_VALIDOS,
    AreaAcceso,
    AreaCatalogo,
    PortalMeResponse,
    PortalUsuarioCreate,
    PortalUsuarioResponse,
    PortalUsuarioUpdate,
    areas_invalidas,
)

router = APIRouter(prefix="/portal", tags=["portal"])


@router.get("/me", response_model=PortalMeResponse)
async def get_me(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    usuario = await repository.get_portal_user(db, current_user.email)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "USUARIO_NO_REGISTRADO",
                "message": "Tu cuenta no tiene acceso a este sistema. Contactá al administrador.",
            },
        )
    return PortalMeResponse(
        email=usuario.email,
        nombre=usuario.nombre,
        rol=usuario.rol,
        secretarias=[s.secretaria for s in usuario.secretarias],
        areas=[AreaAcceso.model_validate(a) for a in usuario.areas],
    )


@router.get("/areas", response_model=dict[str, list[AreaCatalogo]])
async def catalogo_areas(_: AuthUser = Depends(get_current_user)):
    """Áreas de acceso de cada secretaría (spec-portal-areas-de-acceso.md §4)."""
    return {
        sec: [AreaCatalogo(area=area, label=label) for area, label in areas.items()]
        for sec, areas in AREAS_POR_SECRETARIA.items()
    }


def _validar_areas(areas: list[AreaAcceso], secretarias: list[str]) -> None:
    errores = areas_invalidas(areas, secretarias)
    if errores:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "AREA_INVALIDA", "message": "; ".join(errores)},
        )


# --- Administración delegada (spec-portal-administracion-delegada.md, ADR-035) -------------
AREA_ADMIN_USUARIOS = "usuarios"
ROLES_ASIGNABLES_DELEGADO = ("Supervisor", "Operador", "Consulta")


@dataclass
class Administrador:
    """Quién administra y sobre qué alcance. `secretaria=None` = Admin, alcance total."""
    user: AuthUser
    secretaria: str | None

    @property
    def es_admin(self) -> bool:
        return self.secretaria is None


def _require_administrador(current_user: AuthUser = Depends(get_current_user)) -> Administrador:
    if current_user.role == "Admin":
        return Administrador(current_user, None)
    if current_user.role == "Supervisor":
        for sec in current_user.secretarias:
            if current_user.areas.get(sec, {}).get(AREA_ADMIN_USUARIOS) == "edicion":
                return Administrador(current_user, sec)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "PERMISO_INSUFICIENTE",
            "message": "Se requiere rol Admin o Supervisor con Administración de usuarios.",
        },
    )


def _require_admin(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISO_INSUFICIENTE", "message": "Se requiere rol Admin"},
        )
    return current_user


def _en_alcance(adm: Administrador, usuario: object) -> bool:
    """El delegado solo ve y toca usuarios cuya única secretaría es la suya (decisión U3) y con
    un rol que él mismo puede asignar: un Admin o una Autoridad de Vivienda quedan fuera."""
    if adm.es_admin:
        return True
    return (
        [s.secretaria for s in usuario.secretarias] == [adm.secretaria]
        and usuario.rol in ROLES_ASIGNABLES_DELEGADO
    )


def _no_encontrado() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Usuario no encontrado"})


def _error_422(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": code, "message": message},
    )


def _validar_alcance_delegado(
    adm: Administrador, rol: str | None, secretarias: list[str] | None, areas: list[AreaAcceso] | None,
) -> None:
    if adm.es_admin:
        return
    if secretarias is not None and secretarias != [adm.secretaria]:
        raise _error_422("SECRETARIA_FUERA_DE_ALCANCE", f"Solo podés asignar la secretaría {adm.secretaria}.")
    if rol is not None and rol not in ROLES_ASIGNABLES_DELEGADO:
        raise _error_422(
            "ROL_FUERA_DE_ALCANCE", f"Roles que podés asignar: {', '.join(ROLES_ASIGNABLES_DELEGADO)}.",
        )
    if areas and any(a.area == AREA_ADMIN_USUARIOS for a in areas):
        raise _error_422("AREA_FUERA_DE_ALCANCE", "Solo un Admin puede habilitar la Administración de usuarios.")


def _tiene_admin_usuarios(usuario: object) -> bool:
    return any(a.area == AREA_ADMIN_USUARIOS and a.nivel == "edicion" for a in usuario.areas)


def _to_response(u: object) -> PortalUsuarioResponse:
    return PortalUsuarioResponse(
        email=u.email,
        nombre=u.nombre,
        rol=u.rol,
        secretarias=[s.secretaria for s in u.secretarias],
        areas=[AreaAcceso.model_validate(a) for a in u.areas],
        activo=u.activo,
        created_at=u.created_at,
    )


@router.get("/admin/usuarios", response_model=list[PortalUsuarioResponse])
async def list_usuarios(
    adm: Administrador = Depends(_require_administrador),
    db: AsyncSession = Depends(get_db),
):
    return [_to_response(u) for u in await repository.list_usuarios(db) if _en_alcance(adm, u)]


@router.post(
    "/admin/usuarios",
    response_model=PortalUsuarioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_usuario(
    payload: PortalUsuarioCreate,
    adm: Administrador = Depends(_require_administrador),
    db: AsyncSession = Depends(get_db),
):
    current_user = adm.user
    if payload.rol not in ROLES_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ROL_INVALIDO", "message": f"Roles válidos: {', '.join(ROLES_VALIDOS)}"},
        )
    _validar_alcance_delegado(adm, payload.rol, payload.secretarias, payload.areas)
    existing = await repository.get_portal_user_any_status(db, str(payload.email))
    if existing:
        # Al delegado no se le dice en qué secretaría está (puede no ser la suya).
        mensaje = (
            "Ya existe un usuario con ese email" if adm.es_admin
            else "Ese email ya está registrado; pedí el cambio a un administrador."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_DUPLICADO", "message": mensaje},
        )
    _validar_areas(payload.areas, payload.secretarias)
    usuario = await repository.create_usuario(
        db, str(payload.email), payload.nombre, payload.rol, payload.secretarias, current_user.email,
        areas=[a.model_dump() for a in payload.areas],
    )
    await log_audit(
        db, actor=current_user, action="CREATE", resource_type="portal_usuario",
        resource_id=usuario.email[:36], payload=payload.model_dump(mode="json"),
    )
    return _to_response(usuario)


@router.get("/admin/usuarios/{email:path}", response_model=PortalUsuarioResponse)
async def get_usuario(
    email: str,
    adm: Administrador = Depends(_require_administrador),
    db: AsyncSession = Depends(get_db),
):
    usuario = await repository.get_portal_user_any_status(db, email)
    if not usuario or not _en_alcance(adm, usuario):
        raise _no_encontrado()
    return _to_response(usuario)


@router.put("/admin/usuarios/{email:path}", response_model=PortalUsuarioResponse)
async def update_usuario(
    email: str,
    payload: PortalUsuarioUpdate,
    adm: Administrador = Depends(_require_administrador),
    db: AsyncSession = Depends(get_db),
):
    current_user = adm.user
    updates = payload.model_dump(exclude_none=True)
    if "rol" in updates and updates["rol"] not in ROLES_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ROL_INVALIDO", "message": f"Roles válidos: {', '.join(ROLES_VALIDOS)}"},
        )
    actual = await repository.get_portal_user_any_status(db, email)
    if not actual or not _en_alcance(adm, actual):
        raise _no_encontrado()
    if not adm.es_admin:
        if actual.email.lower() == current_user.email.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "AUTO_EDICION", "message": "No podés modificar tu propio usuario."},
            )
        if _tiene_admin_usuarios(actual):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PERMISO_INSUFICIENTE",
                    "message": "Solo un Admin puede modificar a otro administrador de usuarios.",
                },
            )
        _validar_alcance_delegado(adm, payload.rol, payload.secretarias, payload.areas)
    if payload.areas is not None:
        secretarias = payload.secretarias if payload.secretarias is not None else [s.secretaria for s in actual.secretarias]
        _validar_areas(payload.areas, secretarias)
    usuario = await repository.update_usuario(db, email, updates, current_user.email)
    await log_audit(
        db, actor=current_user, action="UPDATE", resource_type="portal_usuario",
        resource_id=usuario.email[:36], payload=payload.model_dump(mode="json", exclude_none=True),
    )
    return _to_response(usuario)


@router.delete("/admin/usuarios/{email:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_usuario(
    email: str,
    current_user: AuthUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    if email.lower() == current_user.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTO_ELIMINACION", "message": "No podés eliminar tu propio usuario."},
        )
    deleted = await repository.delete_usuario(db, email)
    if not deleted:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Usuario no encontrado"})
