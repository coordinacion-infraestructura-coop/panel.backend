"""Estado Técnico de los paneles CC/CH/ML, leído del "Estado del expediente" del checklist.

Los paneles ya no guardan su propio Estado Técnico: lo derivan de
`viv_checklist_tecnico.estado_expediente_id` (spec-estado-tecnico-desde-checklist.md §2).
Vive en un módulo aparte de `service.py` —que importa los services de los 3 paneles— para
que esos services puedan importarlo sin ciclo. Solo lectura: nunca crea filas de checklist.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico.models import ChecklistEstadoHist, ChecklistTecnico

CAMPO_HISTORIAL = "etecnico_checklist"


async def estados_expediente_por_entidad(db: AsyncSession, programa: str) -> dict[str, int | None]:
    """{entidad_id: estado_expediente_id} de todos los checklists del programa."""
    result = await db.execute(
        select(ChecklistTecnico.entidad_id, ChecklistTecnico.estado_expediente_id).where(
            ChecklistTecnico.programa == programa
        )
    )
    return {entidad_id: estado_id for entidad_id, estado_id in result.all()}


async def estado_expediente_de(db: AsyncSession, programa: str, entidad_id: str) -> int | None:
    result = await db.execute(
        select(ChecklistTecnico.estado_expediente_id).where(
            ChecklistTecnico.programa == programa, ChecklistTecnico.entidad_id == entidad_id
        )
    )
    return result.scalar_one_or_none()


async def historial_tecnico(db: AsyncSession, programa: str, entidad_id: str) -> list[dict]:
    """Cambios del estado del expediente de una entidad, con el estado anterior derivado del
    registro previo (`viv_checklist_estado_hist` solo guarda el nuevo). Orden cronológico."""
    result = await db.execute(
        select(ChecklistEstadoHist)
        .join(ChecklistTecnico, ChecklistTecnico.id == ChecklistEstadoHist.checklist_id)
        .where(ChecklistTecnico.programa == programa, ChecklistTecnico.entidad_id == entidad_id)
        .order_by(ChecklistEstadoHist.created_at)
    )
    entradas: list[dict] = []
    anterior: int | None = None
    for h in result.scalars().all():
        entradas.append(
            {
                "id": h.id,
                "campo": CAMPO_HISTORIAL,
                "estado_anterior_id": anterior,
                "estado_nuevo_id": h.estado_expediente_id,
                "created_at": h.created_at,
                "created_by": h.created_by,
            }
        )
        anterior = h.estado_expediente_id
    return entradas


def orden_cronologico(created_at: datetime) -> datetime:
    """Clave de orden que tolera mezclar fechas con y sin tzinfo (SQLite las devuelve naive)."""
    if created_at.tzinfo is None:
        return created_at
    return created_at.astimezone(timezone.utc).replace(tzinfo=None)
