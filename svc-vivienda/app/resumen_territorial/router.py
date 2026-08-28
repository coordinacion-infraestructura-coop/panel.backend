from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLES_ESCRITURA, ROLES_LECTURA, AuthUser, require_roles
from app.database import get_db
from app.resumen_territorial import service
from app.resumen_territorial.schemas import ResumenSnapshotResponse, ResumenTerritorialPayload

# Tuplas locales — `Autoridad` NO se agrega a las constantes compartidas de app.auth
# (mismo criterio que `TecnicoDGV`, ver spec-checklist-tecnico-dgv.md §8 / spec §7.1).
ROLES_LECTURA_RESUMEN = ROLES_LECTURA + ("Autoridad", "TecnicoDGV")
ROLES_ESCRITURA_RESUMEN = ROLES_ESCRITURA + ("Autoridad",)

router = APIRouter()


def _respuesta_para(snapshot, actor: AuthUser) -> ResumenSnapshotResponse:
    payload = service.filtrar_por_visibilidad(
        ResumenTerritorialPayload.model_validate(snapshot.payload),
        rol=actor.role,
        secretarias=actor.secretarias,
    )
    return ResumenSnapshotResponse(
        payload=payload,
        computed_at=snapshot.computed_at,
        computed_by=snapshot.computed_by,
        duracion_ms=snapshot.duracion_ms,
    )


@router.get("/resumen-territorial", response_model=ResumenSnapshotResponse | None)
async def get_resumen(
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_LECTURA_RESUMEN)),
):
    """Último resumen calculado, ya filtrado por la visibilidad del usuario.
    Devuelve `null` si todavía no se calculó ninguno (estado válido, no error)."""
    snapshot = await service.get_last_snapshot(db)
    if snapshot is None:
        return None
    return _respuesta_para(snapshot, actor)


@router.post("/resumen-territorial/actualizar", response_model=ResumenSnapshotResponse)
async def actualizar_resumen(
    db: AsyncSession = Depends(get_db),
    actor: AuthUser = Depends(require_roles(*ROLES_ESCRITURA_RESUMEN)),
):
    """Recalcula el resumen ahora y guarda un snapshot nuevo (no se sobreescribe
    el anterior). Devuelve el resultado ya filtrado por la visibilidad del actor."""
    snapshot = await service.actualizar_resumen(db, actor)
    return _respuesta_para(snapshot, actor)
