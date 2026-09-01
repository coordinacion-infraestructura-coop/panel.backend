"""GET /api/v1/privada/me — alias de compatibilidad.

El frontend viejo consume este endpoint y espera {email, nombre, rol, modulos}.
Se mantiene en v1 (spec §3.7); el frontend nuevo debería migrar a /api/v1/portal/me.
`modulos` siempre [] (el mecanismo usuario_modulos se descartó, ADR-015).
"""
from fastapi import APIRouter, Depends

from app.auth import AuthUser, get_current_user

router = APIRouter(tags=["privada-me"])


@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user)):
    return {
        "email": user.email,
        "nombre": user.nombre,
        "rol": user.role,
        "modulos": [],
    }
