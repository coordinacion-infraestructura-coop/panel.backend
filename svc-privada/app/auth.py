"""Autenticación de svc-privada (ADR-015).

- Valida el JWT de Firebase que reenvía el API Gateway en X-Forwarded-Authorization
  (idéntico a svc-vivienda).
- Resuelve rol + secretarías consultando portal_usuarios. Esa tabla vive en db_vivienda,
  así que svc-privada NO se conecta a esa base: llama a un endpoint interno IAM-only de
  svc-vivienda (`GET {SVC_VIVIENDA_INTERNAL_URL}/internal/portal/usuarios/{email}`),
  autenticándose con un ID token de la SA de runtime (Cloud Run).
- Cualquier fallo del lookup -> rol "invitado" (sin acceso), nunca 500.

Roles de Privada mapean 1:1 a la jerarquía del portal, así que se reutilizan las tuplas
compartidas ROLES_* (no es un rol acotado como TecnicoDGV/Autoridad).
"""
import time
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

SECRETARIA = "privada"


class AuthUser(BaseModel):
    uid: str
    email: str
    role: str
    secretarias: list[str] = []
    nombre: str | None = None


@lru_cache(maxsize=1)
def _google_public_keys_cached(cache_key: int) -> dict:
    response = httpx.get(settings.google_jwks_uri, timeout=10)
    response.raise_for_status()
    return response.json()


def _google_public_keys() -> dict:
    return _google_public_keys_cached(int(time.time() // 3600))


async def _fetch_portal_user(email: str) -> dict | None:
    """Consulta portal_usuarios via el endpoint interno IAM-only de svc-vivienda (ADR-015).

    Devuelve {"rol": str, "secretarias": [str], "nombre": str|None} o None.
    Cualquier error (sin URL configurada, red, 4xx/5xx) -> None (el caller degrada a invitado,
    igual criterio que app/auth.py de svc-vivienda).
    """
    base = settings.svc_vivienda_internal_url.rstrip("/")
    if not base:
        return None
    url = f"{base}/internal/portal/usuarios/{email}"
    headers = {}
    try:
        # ID token de la SA de runtime, audiencia = URL base del servicio invocado.
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        headers["Authorization"] = f"Bearer {id_token.fetch_id_token(GoogleRequest(), base)}"
    except Exception:
        pass  # dev / sin ADC: la llamada irá sin token y probablemente 401/403 -> None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, headers=headers)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


async def get_current_user(request: Request) -> AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTH_TOKEN_INVALIDO", "message": "Token inválido o expirado"},
        headers={"WWW-Authenticate": "Bearer"},
    )

    forwarded = request.headers.get("x-forwarded-authorization", "")
    auth = request.headers.get("authorization", "")
    raw = forwarded if forwarded.startswith("Bearer ") else auth
    if not raw.startswith("Bearer "):
        raise credentials_exception
    token = raw[7:]

    try:
        jwks = _google_public_keys()
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
        if key is None:
            raise credentials_exception
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.gcp_project_id,
            issuer=settings.google_issuer,
        )
        uid = payload.get("sub")
        email = (payload.get("email") or "").lower()
        if uid is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    portal_user = await _fetch_portal_user(email)
    if portal_user:
        role = portal_user.get("rol", "invitado")
        secretarias = portal_user.get("secretarias", [])
        nombre = portal_user.get("nombre")
    else:
        role, secretarias, nombre = "invitado", [], None

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


def require_privada(*roles: str):
    """Además del rol, exige pertenecer a la secretaría 'privada' (o ser Admin)."""

    async def check(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PERMISO_INSUFICIENTE",
                    "message": f"Se requiere uno de los roles: {', '.join(roles)}",
                },
            )
        if user.role != "Admin" and SECRETARIA not in user.secretarias:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PERMISO_INSUFICIENTE",
                    "message": "El usuario no tiene asignada la secretaría 'privada'.",
                },
            )
        return user

    return check


ROLES_LECTURA = ("Admin", "Supervisor", "Operador", "Consulta")
ROLES_ESCRITURA = ("Admin", "Supervisor", "Operador")
ROLES_TRANSICION = ("Admin", "Supervisor")
ROLES_ELIMINACION = ("Admin",)
ROLES_ADMIN = ("Admin",)
