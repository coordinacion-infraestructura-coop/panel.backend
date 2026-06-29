from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.programas import repository
from app.programas.schemas import ProgramaCreate, ProgramaEstadisticas, ProgramaResponse

PROGRAMAS_SEED = [
    {"codigo": "CORDOBA_HOGAR", "nombre": "Córdoba Hogar", "descripcion": "Programa habitacional Córdoba Hogar", "requiere_ingreso_max": True},
    {"codigo": "MI_LUGAR", "nombre": "Mi Lugar", "descripcion": "Programa de expropiaciones Mi Lugar", "requiere_ingreso_max": True},
    {"codigo": "CORDON_CUNETA", "nombre": "Cordón Cuneta", "descripcion": "Programa de pavimentación Cordón Cuneta", "requiere_ingreso_max": False},
    {"codigo": "LOTEOS", "nombre": "Programa de Loteos", "descripcion": "Loteos por expropiaciones, tierras provinciales, municipales y cooperativas", "requiere_ingreso_max": False},
]


async def listar_programas(db: AsyncSession) -> list[ProgramaResponse]:
    programas = await repository.get_all(db)
    return [ProgramaResponse.model_validate(p) for p in programas]


async def get_programa(db: AsyncSession, programa_id: str) -> ProgramaResponse:
    programa = await repository.get_by_id(db, programa_id)
    if not programa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Programa {programa_id} no encontrado"},
        )
    return ProgramaResponse.model_validate(programa)


async def get_estadisticas(db: AsyncSession, programa_id: str) -> ProgramaEstadisticas:
    programa = await repository.get_by_id(db, programa_id)
    if not programa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Programa {programa_id} no encontrado"},
        )
    result = await db.execute(
        text("""
            SELECT estado, COUNT(*) as count
            FROM viv_expedientes
            WHERE programa_id = :programa_id AND deleted_at IS NULL
            GROUP BY estado
        """),
        {"programa_id": programa_id},
    )
    rows = result.fetchall()
    por_estado = {row.estado: row.count for row in rows}
    total = sum(por_estado.values())
    return ProgramaEstadisticas(
        programa_id=programa.id,
        codigo=programa.codigo,
        nombre=programa.nombre,
        total_expedientes=total,
        por_estado=por_estado,
    )


async def seed_programas(db: AsyncSession) -> None:
    """Inserta los programas iniciales si no existen."""
    for data in PROGRAMAS_SEED:
        existing = await repository.get_by_codigo(db, data["codigo"])
        if not existing:
            await repository.create(db, data)
