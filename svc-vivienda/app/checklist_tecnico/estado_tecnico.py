"""Estado Técnico de los paneles CC/CH/ML, leído del "Estado del expediente" del checklist.

Los paneles ya no guardan su propio Estado Técnico: lo derivan de
`viv_checklist_tecnico.estado_expediente_id` (spec-estado-tecnico-desde-checklist.md §2).
Vive en un módulo aparte de `service.py` —que importa los services de los 3 paneles— para
que esos services puedan importarlo sin ciclo. Solo lectura: nunca crea filas de checklist.
"""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico import catalog
from app.checklist_tecnico.models import (
    CatalogoItemEstado,
    ChecklistAvanceMedicion,
    ChecklistEstadoHist,
    ChecklistItem,
    ChecklistObraHito,
    ChecklistTecnico,
)

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


# ── Avance de obra (spec-checklist-tecnico-dgv.md v1.6.0 §5.6 / §6-bis) ──────────────

def avance_vigente(mediciones: list[tuple[date, datetime, int]]) -> tuple[int, date] | None:
    """(porcentaje, fecha) de la medición de fecha más reciente (desempate por created_at).
    `mediciones` = [(fecha_medicion, created_at, porcentaje)] ya sin las borradas."""
    if not mediciones:
        return None
    fecha, _, pct = max(mediciones, key=lambda m: (m[0], orden_cronologico(m[1])))
    return pct, fecha


def fecha_medicion_hito(tipo: str, mediciones: list[tuple[date, datetime, int]]) -> date | None:
    """Primera fecha en que una medición alcanzó el umbral del hito; None si ninguna (o anticipo)."""
    umbral = catalog.HITOS_UMBRAL.get(tipo)
    if umbral is None:
        return None
    fechas = [f for f, _, pct in mediciones if pct >= umbral]
    return min(fechas) if fechas else None


def _resumen_obra(
    mediciones: list[tuple[date, datetime, int]],
    pagos: dict[str, date | None],
    monto_convenio: float | None,
    fecha_fin_obra: date | None,
) -> dict:
    vigente = avance_vigente(mediciones)
    return {
        "avance_obra_pct": vigente[0] if vigente else None,
        "avance_obra_fecha": vigente[1] if vigente else None,
        "fecha_fin_obra": fecha_fin_obra,
        "hitos_obra": [
            {
                "tipo": tipo,
                "monto": catalog.monto_hito(tipo, monto_convenio),
                "fecha_medicion": fecha_medicion_hito(tipo, mediciones),
                "fecha_acreditado": pagos.get(tipo),
            }
            for tipo in catalog.HITOS_TIPOS
        ],
    }


RESUMEN_OBRA_VACIO: dict = {
    "avance_obra_pct": None, "avance_obra_fecha": None, "fecha_fin_obra": None, "hitos_obra": None,
    "doc_completos": None, "doc_total": None, "doc_iniciado": False,
}


def resumen_documentacion(programa: str, valores: list[tuple[int, int | None, str]]) -> dict:
    """Completitud de la documentación de un checklist, con la misma regla que el Resumen
    Territorial (`aggregations.items_faltantes`): los "No Aplica" salen del total.
    `valores` = [(item_num, sub_item_num, 'completo'|'no_aplica'|'pendiente')].
    Spec: spec-vivienda-tablero-analitico.md §4.5."""
    from app.resumen_territorial.aggregations import items_faltantes

    total, faltan, _, iniciado = items_faltantes(
        [{"item_num": n, "sub_item_num": sub, "valor": v} for n, sub, v in valores], programa
    )
    return {"doc_completos": total - faltan, "doc_total": total, "doc_iniciado": iniciado}


async def valores_items(db: AsyncSession, checklist_ids: list[str]) -> dict[str, list[tuple[int, int | None, str]]]:
    """{checklist_id: [(item_num, sub_item_num, valor)]} — 2 consultas, sin N+1."""
    if not checklist_ids:
        return {}
    estados = (
        await db.execute(
            select(CatalogoItemEstado.id, CatalogoItemEstado.es_completo, CatalogoItemEstado.excluye_completitud)
        )
    ).all()
    completo = {e.id for e in estados if e.es_completo}
    no_aplica = {e.id for e in estados if e.excluye_completitud}
    out: dict[str, list[tuple[int, int | None, str]]] = {}
    for chk_id, item_num, sub, estado_id in (
        await db.execute(
            select(
                ChecklistItem.checklist_id, ChecklistItem.item_num, ChecklistItem.sub_item_num,
                ChecklistItem.item_estado_id,
            ).where(ChecklistItem.checklist_id.in_(checklist_ids))
        )
    ).all():
        valor = "completo" if estado_id in completo else "no_aplica" if estado_id in no_aplica else "pendiente"
        out.setdefault(chk_id, []).append((item_num, sub, valor))
    return out


async def avance_por_entidad(
    db: AsyncSession, programa: str, montos: dict[str, float | None], entidad_id: str | None = None
) -> dict[str, dict]:
    """{entidad_id: {avance_obra_pct, avance_obra_fecha, fecha_fin_obra, hitos_obra,
    doc_completos, doc_total, doc_iniciado}} de los checklists del programa (o de una sola
    entidad). 5 consultas en total, sin N+1; nunca crea filas. `montos` = {entidad_id: monto
    del convenio} para calcular el monto de cada hito.
    Una entidad sin fila de checklist no aparece (el panel usa `RESUMEN_OBRA_VACIO`)."""
    q = select(ChecklistTecnico.id, ChecklistTecnico.entidad_id, ChecklistTecnico.fecha_fin_obra).where(
        ChecklistTecnico.programa == programa
    )
    if entidad_id is not None:
        q = q.where(ChecklistTecnico.entidad_id == entidad_id)
    checklists = (await db.execute(q)).all()
    if not checklists:
        return {}
    ids = [c.id for c in checklists]

    mediciones: dict[str, list[tuple[date, datetime, int]]] = {}
    for chk_id, fecha, created_at, pct in (
        await db.execute(
            select(
                ChecklistAvanceMedicion.checklist_id,
                ChecklistAvanceMedicion.fecha_medicion,
                ChecklistAvanceMedicion.created_at,
                ChecklistAvanceMedicion.porcentaje,
            ).where(
                ChecklistAvanceMedicion.checklist_id.in_(ids),
                ChecklistAvanceMedicion.deleted_at.is_(None),
            )
        )
    ).all():
        mediciones.setdefault(chk_id, []).append((fecha, created_at, pct))

    pagos: dict[str, dict[str, date | None]] = {}
    for chk_id, tipo, fecha in (
        await db.execute(
            select(
                ChecklistObraHito.checklist_id, ChecklistObraHito.tipo, ChecklistObraHito.fecha_acreditado
            ).where(ChecklistObraHito.checklist_id.in_(ids))
        )
    ).all():
        pagos.setdefault(chk_id, {})[tipo] = fecha

    items = await valores_items(db, ids)
    return {
        c.entidad_id: {
            **_resumen_obra(
                mediciones.get(c.id, []), pagos.get(c.id, {}), montos.get(c.entidad_id), c.fecha_fin_obra
            ),
            **resumen_documentacion(programa, items.get(c.id, [])),
        }
        for c in checklists
    }


async def avance_de(db: AsyncSession, programa: str, entidad_id: str, monto: float | None) -> dict:
    """Mismo resumen que `avance_por_entidad`, para una sola entidad (respuestas de create/update)."""
    res = await avance_por_entidad(db, programa, {entidad_id: monto}, entidad_id)
    return res.get(entidad_id, RESUMEN_OBRA_VACIO)


def aplicar_obra(out, obra: dict | None) -> None:
    """Vuelca el resumen de `avance_por_entidad` (obra + documentación) sobre la respuesta de
    un panel (CC/CH/ML)."""
    from app.checklist_tecnico.schemas import HitoObraPanel

    obra = obra or RESUMEN_OBRA_VACIO
    out.avance_obra_pct = obra["avance_obra_pct"]
    out.avance_obra_fecha = obra["avance_obra_fecha"]
    out.fecha_fin_obra = obra["fecha_fin_obra"]
    out.doc_completos = obra["doc_completos"]
    out.doc_total = obra["doc_total"]
    out.doc_iniciado = obra["doc_iniciado"]
    out.hitos_obra = (
        [HitoObraPanel(**h) for h in obra["hitos_obra"]] if obra["hitos_obra"] is not None else None
    )


def _monto(entidad) -> float | None:
    return float(entidad.monto) if entidad.monto is not None else None


async def avance_por_entidades(db: AsyncSession, programa: str, entidades) -> dict[str, dict]:
    """Atajo para los listados de panel: arma `montos` a partir de las entidades ORM."""
    return await avance_por_entidad(db, programa, {e.id: _monto(e) for e in entidades})


async def avance_de_entidad(db: AsyncSession, programa: str, entidad) -> dict:
    return await avance_de(db, programa, entidad.id, _monto(entidad))
