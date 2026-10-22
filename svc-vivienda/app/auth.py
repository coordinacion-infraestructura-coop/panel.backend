import time
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db


class AuthUser(BaseModel):
    uid: str
    email: str
    role: str                     # kept as 'role' — audit.py uses actor.role
    secretarias: list[str] = []
    nombre: str | None = None
    # {secretaria: {area: "lectura" | "edicion"}} — spec-portal-areas-de-acceso.md
    areas: dict[str, dict[str, str]] = {}


@lru_cache(maxsize=1)
def _get_google_public_keys_cached(cache_key: int) -> dict:
    response = httpx.get(settings.google_jwks_uri, timeout=10)
    response.raise_for_status()
    return response.json()


def _get_google_public_keys() -> dict:
    cache_key = int(time.time() // 3600)
    return _get_google_public_keys_cached(cache_key)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTH_TOKEN_INVALIDO", "message": "Token inválido o expirado"},
        headers={"WWW-Authenticate": "Bearer"},
    )

    # API Gateway reemplaza Authorization con el token del SA de backend.
    # El JWT original del usuario llega en X-Forwarded-Authorization.
    forwarded = request.headers.get("x-forwarded-authorization", "")
    auth = request.headers.get("authorization", "")
    raw = forwarded if forwarded.startswith("Bearer ") else auth

    if not raw.startswith("Bearer "):
        raise credentials_exception

    token = raw[7:]

    try:
        jwks = _get_google_public_keys()
        header = jwt.get_unverified_header(token)
        key = next(
            (k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")),
            None,
        )
        if key is None:
            raise credentials_exception

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.gcp_project_id,
            issuer=settings.google_issuer,
        )
        uid: str = payload.get("sub")
        email: str = payload.get("email", "")

        if uid is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    # DB lookup para rol y secretarías (importación local evita dependencia circular).
    # Try/except: si la tabla no existe aún (migración pendiente) devuelve invitado en lugar de 500.
    try:
        from app.portal.repository import get_portal_user

        portal_user = await get_portal_user(db, email)
        if portal_user:
            role = portal_user.rol
            secretarias = [s.secretaria for s in portal_user.secretarias]
            nombre = portal_user.nombre
            areas: dict[str, dict[str, str]] = {}
            for a in portal_user.areas:
                areas.setdefault(a.secretaria, {})[a.area] = a.nivel
        else:
            role = "invitado"
            secretarias = []
            nombre = None
            areas = {}
    except Exception:
        role = "invitado"
        secretarias = []
        nombre = None
        areas = {}

    return AuthUser(uid=uid, email=email, role=role, secretarias=secretarias, nombre=nombre, areas=areas)


def require_roles(*roles: str):
    async def check_role(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PERMISO_INSUFICIENTE",
                    "message": f"Se requiere uno de los roles: {', '.join(roles)}",
                },
            )
        return user
    return check_role


ROLES_LECTURA = ("Admin", "Supervisor", "Operador", "Consulta", "Autoridad")
ROLES_ESCRITURA = ("Admin", "Supervisor", "Operador")
ROLES_TRANSICION = ("Admin", "Supervisor")
ROLES_ELIMINACION = ("Admin",)
ROLES_ADMIN = ("Admin",)


SECRETARIAS_COMUNICACIONES = frozenset({"infraestructura", "supervision"})


def nivel_de_area(user: AuthUser, secretaria: str, areas: tuple[str, ...]) -> str | None:
    """Mejor nivel ("edicion" > "lectura") que tiene el usuario en alguna de `areas`
    (todas las de la secretaría si `areas` está vacío). Admin: siempre "edicion"."""
    if user.role == "Admin":
        return "edicion"
    if secretaria not in user.secretarias:
        return None
    propias = user.areas.get(secretaria, {})
    niveles = [nivel for area, nivel in propias.items() if not areas or area in areas]
    if "edicion" in niveles:
        return "edicion"
    return "lectura" if niveles else None


def _sin_area(areas: tuple[str, ...], nivel: str) -> HTTPException:
    que = ", ".join(areas) if areas else "alguna área"
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "AREA_SIN_ACCESO",
            "message": f"Se requiere acceso de {nivel} a {que} de la secretaría.",
        },
    )


def require_area(
    *areas: str,
    secretaria: str = "vivienda",
    lectura_comunicaciones: bool = False,
    abierto_a_autoridad: bool = False,
):
    """Lectura de un módulo: el usuario tiene que tener la secretaría y alguna de `areas`
    (cualquiera de la secretaría si no se pasa ninguna). Se usa como dependencia del router
    entero (spec-portal-areas-de-acceso.md §5).

    `lectura_comunicaciones`: los paneles CC/CH/ML siguen abiertos en lectura a Infraestructura y
    Supervisión, que cargan comunicaciones en ellos (`require_comunicaciones_write`).
    `abierto_a_autoridad`: tableros transversales que `Autoridad` ve sin tener la secretaría
    (spec-vivienda-tablero-analitico.md)."""
    async def check(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if nivel_de_area(user, secretaria, areas):
            return user
        if abierto_a_autoridad and user.role == "Autoridad":
            return user
        if lectura_comunicaciones and SECRETARIAS_COMUNICACIONES & set(user.secretarias):
            return user
        raise _sin_area(areas, "lectura")
    return check


def require_edicion(areas: tuple[str, ...], *roles: str, secretaria: str = "vivienda"):
    """Escritura: rol en `roles` y nivel "edicion" en alguna de `areas`. El permiso efectivo es
    el menor de los dos (un Consulta con un área en edición sigue sin escribir)."""
    check_rol = require_roles(*roles)

    async def check(user: AuthUser = Depends(check_rol)) -> AuthUser:
        if nivel_de_area(user, secretaria, areas) != "edicion":
            raise _sin_area(areas, "edición")
        return user
    return check


def require_comunicaciones_write():
    """Permite escribir comunicaciones si tiene rol de escritura O pertenece a infraestructura/supervision."""
    async def check(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role in ROLES_ESCRITURA or SECRETARIAS_COMUNICACIONES & set(user.secretarias):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PERMISO_INSUFICIENTE",
                "message": "Se requiere rol Operador o superior, o pertenecer a Infraestructura o Supervisión.",
            },
        )
    return check
