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


def _require_admin(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISO_INSUFICIENTE", "message": "Se requiere rol Admin"},
        )
    return current_user


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
    _: AuthUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    return [_to_response(u) for u in await repository.list_usuarios(db)]


@router.post(
    "/admin/usuarios",
    response_model=PortalUsuarioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_usuario(
    payload: PortalUsuarioCreate,
    current_user: AuthUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    if payload.rol not in ROLES_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ROL_INVALIDO", "message": f"Roles válidos: {', '.join(ROLES_VALIDOS)}"},
        )
    existing = await repository.get_portal_user_any_status(db, str(payload.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_DUPLICADO", "message": "Ya existe un usuario con ese email"},
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
    _: AuthUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    usuario = await repository.get_portal_user_any_status(db, email)
    if not usuario:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Usuario no encontrado"})
    return _to_response(usuario)


@router.put("/admin/usuarios/{email:path}", response_model=PortalUsuarioResponse)
async def update_usuario(
    email: str,
    payload: PortalUsuarioUpdate,
    current_user: AuthUser = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    updates = payload.model_dump(exclude_none=True)
    if "rol" in updates and updates["rol"] not in ROLES_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ROL_INVALIDO", "message": f"Roles válidos: {', '.join(ROLES_VALIDOS)}"},
        )
    actual = await repository.get_portal_user_any_status(db, email)
    if not actual:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Usuario no encontrado"})
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
