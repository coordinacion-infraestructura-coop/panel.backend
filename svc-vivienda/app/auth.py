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
        else:
            role = "invitado"
            secretarias = []
            nombre = None
    except Exception:
        role = "invitado"
        secretarias = []
        nombre = None

    return AuthUser(uid=uid, email=email, role=role, secretarias=secretarias, nombre=nombre)


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


ROLES_LECTURA = ("Admin", "Supervisor", "Operador", "Consulta")
ROLES_ESCRITURA = ("Admin", "Supervisor", "Operador")
ROLES_TRANSICION = ("Admin", "Supervisor")
ROLES_ELIMINACION = ("Admin",)
ROLES_ADMIN = ("Admin",)


SECRETARIAS_COMUNICACIONES = frozenset({"infraestructura", "supervision"})


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
