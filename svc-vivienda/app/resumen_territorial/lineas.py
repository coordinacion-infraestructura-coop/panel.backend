"""Líneas de programa de Vivienda (CC/CH/ML), leídas de `db_vivienda`.

Las usan dos consumidores con la misma lógica (ADR-030):
- `service.compute_resumen_territorial`, que las agrupa en el snapshot del Resumen Territorial;
- `app/tablero_analitico`, que las sirve en vivo al Tablero analítico de Vivienda.

Spec: docs/files/spec-vivienda-tablero-analitico.md §4.1
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico.models import (
    CatalogoEstadoExpediente,
    CatalogoItemEstado,
    ChecklistItem,
    ChecklistTecnico,
)
from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar, PedidoCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta, PedidoCordonCuneta
from app.geo.models import GeoLocalidad
from app.mi_lugar.models import EstadoML, PedidoML, ProyectoML
from app.resumen_territorial import aggregations


# ── Helpers de carga ─────────────────────────────────────────────────────────

async def geo_rows(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(GeoLocalidad))
    return [
        {
            "departamento": g.departamento, "localidad": g.localidad,
            "id_geo": g.id_geo, "activo": g.activo,
            "lat_centro": float(g.lat_centro) if g.lat_centro is not None else None,
            "lon_centro": float(g.lon_centro) if g.lon_centro is not None else None,
        }
        for g in result.scalars().all()
    ]


def _catalogo(rows) -> dict[int, dict]:
    return {
        c.id: {"label": c.label, "bg": c.bg, "text_color": c.text_color}
        for c in rows
    }


def _estado_fields(entidad, catalogo: dict[int, dict], tecnico_label: str | None) -> dict:
    est = catalogo.get(entidad.estado_general)
    return {
        "estado_general_id": entidad.estado_general,
        "estado_general_label": est["label"] if est else None,
        "estado_general_bg": est["bg"] if est else None,
        "estado_general_text_color": est["text_color"] if est else None,
        "subestados": {
            "juridico": (catalogo.get(entidad.ejuridico) or {}).get("label"),
            # El Técnico es el estado del expediente del checklist, no la columna del panel
            # (spec-estado-tecnico-desde-checklist.md §3.5).
            "tecnico": tecnico_label,
            "financiero": (catalogo.get(entidad.efinanciero) or {}).get("label"),
        },
    }


def _pedidos_por_entidad(rows, fk: str) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = {}
    for p in rows:
        d.setdefault(getattr(p, fk), []).append(
            {
                "fecha_pedido": p.fecha_pedido,
                "created_at": p.created_at,
                "descripcion": p.descripcion,
                "secretaria": p.secretaria,
                "created_by": p.created_by,
                "created_by_nombre": p.created_by_nombre,
            }
        )
    return d


# ── Líneas ───────────────────────────────────────────────────────────────────

async def lineas_vivienda(db: AsyncSession) -> list[dict]:
    """Una línea por expediente de CC/CH/ML: `{departamento, nombre_localidad, id_geo, programa}`,
    con `programa` en la forma de `ResumenPrograma`."""
    cc_rows = (
        await db.execute(select(MunicipioCordonCuneta).where(MunicipioCordonCuneta.deleted_at.is_(None)))
    ).scalars().all()
    ch_rows = (
        await db.execute(select(LocalidadCordobaHogar).where(LocalidadCordobaHogar.deleted_at.is_(None)))
    ).scalars().all()
    ml_rows = (
        await db.execute(select(ProyectoML).where(ProyectoML.deleted_at.is_(None)))
    ).scalars().all()

    cc_cat = _catalogo((await db.execute(select(EstadoCordonCuneta))).scalars().all())
    ch_cat = _catalogo((await db.execute(select(EstadoCordobaHogar))).scalars().all())
    ml_cat = _catalogo((await db.execute(select(EstadoML))).scalars().all())

    # Checklist técnico: todas las filas + ítems, agrupados en Python. No se crean filas.
    checklists = (await db.execute(select(ChecklistTecnico))).scalars().all()
    chk_by_ent = {(c.programa, c.entidad_id): c.id for c in checklists}
    exp_labels = {
        e.id: e.label for e in (await db.execute(select(CatalogoEstadoExpediente))).scalars().all()
    }
    tecnico_by_ent = {
        (c.programa, c.entidad_id): exp_labels.get(c.estado_expediente_id) for c in checklists
    }
    # "completo" ya no es un literal: es el/los estado(s) del catálogo con es_completo=True.
    completo_ids = {
        e.id
        for e in (
            await db.execute(select(CatalogoItemEstado).where(CatalogoItemEstado.es_completo.is_(True)))
        ).scalars().all()
    }
    # "No Proyectado / No Aplica" (excluye_completitud) queda fuera del total y de los faltantes.
    no_aplica_ids = {
        e.id
        for e in (
            await db.execute(
                select(CatalogoItemEstado).where(CatalogoItemEstado.excluye_completitud.is_(True))
            )
        ).scalars().all()
    }
    items_by_chk: dict[str, list[dict]] = {}
    for it in (await db.execute(select(ChecklistItem))).scalars().all():
        if it.item_estado_id in completo_ids:
            valor = "completo"
        elif it.item_estado_id in no_aplica_ids:
            valor = "no_aplica"
        else:
            valor = "pendiente"
        items_by_chk.setdefault(it.checklist_id, []).append(
            {"item_num": it.item_num, "sub_item_num": it.sub_item_num, "valor": valor}
        )

    cc_ped = _pedidos_por_entidad(
        (await db.execute(select(PedidoCordonCuneta))).scalars().all(), "municipio_id"
    )
    ch_ped = _pedidos_por_entidad(
        (await db.execute(select(PedidoCordobaHogar))).scalars().all(), "localidad_id"
    )
    ml_ped = _pedidos_por_entidad(
        (await db.execute(select(PedidoML))).scalars().all(), "proyecto_id"
    )

    def _linea_vivienda(programa, prog_cod, entidad, nombre, catalogo, pedidos_map, detalle=None):
        chk_id = chk_by_ent.get((prog_cod, entidad.id))
        total, faltan, faltantes, iniciado = aggregations.items_faltantes(
            items_by_chk.get(chk_id, []) if chk_id else [], prog_cod
        )
        prog = {
            "area": "vivienda",
            "programa": programa,
            "programa_label": aggregations.PROGRAMA_LABEL[programa],
            "entidad_id": entidad.id,
            "detalle": detalle,
            **_estado_fields(entidad, catalogo, tecnico_by_ent.get((prog_cod, entidad.id))),
            "checklist_total": total,
            "checklist_faltan": faltan,
            "checklist_iniciado": iniciado,
            "checklist_faltantes": faltantes,
            "ultima_comunicacion": aggregations.ultima_comunicacion(pedidos_map.get(entidad.id, [])),
            "monto": float(entidad.monto) if entidad.monto is not None else None,
            "expediente": entidad.expediente,
        }
        return {
            "departamento": entidad.departamento,
            "nombre_localidad": nombre,
            "id_geo": entidad.localidad_id,
            "programa": prog,
        }

    lineas: list[dict] = []
    for m in cc_rows:
        lineas.append(_linea_vivienda("cordon_cuneta", "cc", m, m.municipio, cc_cat, cc_ped))
    for loc in ch_rows:
        lineas.append(_linea_vivienda("cordoba_hogar", "ch", loc, loc.localidad, ch_cat, ch_ped))
    for pr in ml_rows:
        lineas.append(
            _linea_vivienda(
                "mi_lugar", "ml", pr, pr.localidad_nombre or pr.nombre, ml_cat, ml_ped, detalle=pr.nombre
            )
        )

    return lineas
