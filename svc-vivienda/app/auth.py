import time
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

security = HTTPBearer()


class AuthUser(BaseModel):
    uid: str
    email: str
    role: str
    secretaria: str | None = None


@lru_cache(maxsize=1)
def _get_google_public_keys_cached(cache_key: int) -> dict:
    """Cachea las public keys de Google, con TTL de 1 hora."""
    response = httpx.get(settings.google_jwks_uri, timeout=10)
    response.raise_for_status()
    return response.json()


def _get_google_public_keys() -> dict:
    cache_key = int(time.time() // 3600)
    return _get_google_public_keys_cached(cache_key)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthUser:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTH_TOKEN_INVALIDO", "message": "Token inválido o expirado"},
        headers={"WWW-Authenticate": "Bearer"},
    )
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
        role: str = payload.get("role", "operador")
        secretaria: str | None = payload.get("secretaria")

        if uid is None:
            raise credentials_exception

        return AuthUser(uid=uid, email=email, role=role, secretaria=secretaria)

    except JWTError:
        raise credentials_exception


def require_roles(*roles: str):
    """Dependencia que exige que el usuario tenga uno de los roles especificados."""
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


ROLES_LECTURA = ("ministro", "secretario", "director", "operador", "admin_sistema")
ROLES_ESCRITURA = ("secretario", "director", "operador", "admin_sistema")
ROLES_TRANSICION = ("secretario", "director", "admin_sistema")
