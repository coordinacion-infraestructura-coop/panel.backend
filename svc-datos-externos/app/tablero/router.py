"""Tablero de Gobierno — reemplazo del Looker "Tablero - Min. de Gobierno"
(spec-tablero-gobierno-panel.md, ADR-028).

Todo el tablero es solo para `Admin` y `Autoridad` (decisión del usuario 2026-10-19), sin
chequeo de secretaría: es una vista transversal, como resumen_territorial. Cualquier otro rol
recibe 403.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, require_roles
from app.database import get_db
from app.tablero import service
from app.tablero.schemas import TableroMetaResponse

ROLES_TABLERO = ("Admin", "Autoridad")

router = APIRouter(prefix="/tablero")


@router.get("/meta", response_model=TableroMetaResponse)
async def tablero_meta(
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*ROLES_TABLERO)),
) -> TableroMetaResponse:
    """Filtros (localidades, años) y frescura de cada fuente, para la barra común del tablero."""
    return await service.get_meta(db)
