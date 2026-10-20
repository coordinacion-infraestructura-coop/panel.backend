"""Tablero de Gobierno — reemplazo del Looker "Tablero - Min. de Gobierno"
(spec-tablero-gobierno-panel.md, ADR-028).

Todo el tablero es solo para `Admin` y `Autoridad` (decisión del usuario 2026-10-19), sin
chequeo de secretaría: es una vista transversal, como resumen_territorial. Cualquier otro rol
recibe 403.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser, require_roles
from app.database import get_db
from app.tablero import service
from app.tablero.schemas import (
    FodemeepResponse,
    FommepResponse,
    InicioResponse,
    ResumenResponse,
    TableroMetaResponse,
    TransferenciasResponse,
)

ROLES_TABLERO = ("Admin", "Autoridad")

router = APIRouter(prefix="/tablero")


@router.get("/meta", response_model=TableroMetaResponse)
async def tablero_meta(
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*ROLES_TABLERO)),
) -> TableroMetaResponse:
    """Filtros (localidades, años) y frescura de cada fuente, para la barra común del tablero."""
    return await service.get_meta(db)


_ANIO = Query(..., ge=2000, le=2100)
_CODIGOS = Query(None, description="Códigos INDEC del filtro territorial (vacío = toda la provincia)")


@router.get("/inicio", response_model=InicioResponse)
async def tablero_inicio(
    anio: int = _ANIO,
    codigo_indec: list[str] | None = _CODIGOS,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*ROLES_TABLERO)),
) -> InicioResponse:
    """KPIs de la portada y transferido por habitante por departamento (Etapa 1)."""
    return await service.get_inicio(db, anio, codigo_indec)


@router.get(
    "/transferencias/{seccion}",
    response_model=TransferenciasResponse | FodemeepResponse | FommepResponse | ResumenResponse,
)
async def tablero_transferencias(
    seccion: str,
    anio: int = _ANIO,
    codigo_indec: list[str] | None = _CODIGOS,
    db: AsyncSession = Depends(get_db),
    _user: AuthUser = Depends(require_roles(*ROLES_TABLERO)),
) -> TransferenciasResponse | FodemeepResponse | FommepResponse | ResumenResponse:
    """`coparticipacion` y `fofindes`: serie mensual, acumulado y variación; desde la planilla de
    Gobierno cuando tiene el año (quincenas, neto, descuentos, retenciones, % a sueldos) y si no
    desde Transparencia. `fodemeep`, `fommep` y `resumen`: solo planillas (Etapa 2,
    spec-datos-externos-fase2-transferencias.md §5)."""
    if seccion in service.SECCIONES_TRANSFERENCIAS:
        return await service.get_transferencias(db, seccion, anio, codigo_indec)
    if seccion in service.SECCIONES_PLANILLAS:
        return await service.get_seccion_planilla(db, seccion, anio, codigo_indec)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "SECCION_INEXISTENTE", "message": f"Sección de transferencias desconocida: {seccion}"},
    )
