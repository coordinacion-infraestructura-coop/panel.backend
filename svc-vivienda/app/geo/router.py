from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_TRANSICION, AuthUser, require_roles
from app.database import get_db
from app.geo import service
from app.geo.schemas import DuplicadosResponse

router = APIRouter(prefix="/geo", tags=["geo"])


@router.get("/duplicados", response_model=DuplicadosResponse)
async def duplicados(
    modulo: Literal["cordon_cuneta", "cordoba_hogar", "mi_lugar"],
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_TRANSICION)),
):
    grupos = await service.detectar_duplicados(db, modulo)
    return {"grupos": grupos}
