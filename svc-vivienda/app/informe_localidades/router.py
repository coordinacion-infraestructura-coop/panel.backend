from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, require_roles
from app.database import get_db
from app.informe_localidades import service
from app.informe_localidades.schemas import LocalidadInformeRow
from app.programas.router import ROLES_LECTURA_TABLERO

router = APIRouter()


@router.get("/informe-localidades", response_model=list[LocalidadInformeRow])
async def informe_localidades(
    db: AsyncSession = Depends(get_db),
    _: AuthUser = Depends(require_roles(*ROLES_LECTURA_TABLERO)),
):
    """Informe "Localidades por Departamento" (spec-informe-localidades-departamento.md):
    una fila por localidad activa del padrón geográfico, con Cordón Cuneta,
    Córdoba Hogar y habitantes (federado desde svc-privada). Calculado on-the-fly,
    sin snapshot. Mismos roles que el Tablero de Programas — el botón de descarga
    vive en esa misma pantalla."""
    return await service.compute_informe(db)
