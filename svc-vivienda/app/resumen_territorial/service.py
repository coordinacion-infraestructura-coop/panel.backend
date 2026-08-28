"""Orquestación del Resumen Territorial — toca DB y llama al API Gateway.

Espeja `app/informes/service.py`: funciones que cargan datos y delegan la
lógica en `aggregations.py` (puro). Convención "panel module": sin repository,
queries inline, sólo audit log, sin Pub/Sub.

Spec: docs/files/spec-resumen-territorial.md §6
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.checklist_tecnico.models import ChecklistItem, ChecklistTecnico
from app.config import settings
from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar, PedidoCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta, PedidoCordonCuneta
from app.geo.models import GeoLocalidad
from app.mi_lugar.models import EstadoML, PedidoML, ProyectoML
from app.resumen_territorial import aggregations
from app.resumen_territorial.models import ResumenTerritorialSnapshot
from app.resumen_territorial.schemas import ResumenLocalidad, ResumenTerritorialPayload

logger = logging.getLogger(__name__)

_VER_TODO = ("Admin", "Autoridad")


# ── Helpers de carga ─────────────────────────────────────────────────────────

async def _geo_rows(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(GeoLocalidad))
    return [
        {"departamento": g.departamento, "localidad": g.localidad}
        for g in result.scalars().all()
    ]


def _catalogo(rows) -> dict[int, dict]:
    return {
        c.id: {"label": c.label, "bg": c.bg, "text_color": c.text_color}
        for c in rows
    }


def _estado_fields(entidad, catalogo: dict[int, dict]) -> dict:
    est = catalogo.get(entidad.estado_general)
    return {
        "estado_general_id": entidad.estado_general,
        "estado_general_label": est["label"] if est else None,
        "estado_general_bg": est["bg"] if est else None,
        "estado_general_text_color": est["text_color"] if est else None,
        "subestados": {
            "juridico": (catalogo.get(entidad.ejuridico) or {}).get("label"),
            "tecnico": (catalogo.get(entidad.etecnico) or {}).get("label"),
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


# ── Cómputo ──────────────────────────────────────────────────────────────────

async def compute_resumen_territorial(db: AsyncSession) -> ResumenTerritorialPayload:
    geo = await _geo_rows(db)

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
    chk_by_ent = {
        (c.programa, c.entidad_id): c.id
        for c in (await db.execute(select(ChecklistTecnico))).scalars().all()
    }
    items_by_chk: dict[str, list[dict]] = {}
    for it in (await db.execute(select(ChecklistItem))).scalars().all():
        items_by_chk.setdefault(it.checklist_id, []).append(
            {"item_num": it.item_num, "sub_item_num": it.sub_item_num, "valor": it.valor}
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
            **_estado_fields(entidad, catalogo),
            "checklist_total": total,
            "checklist_faltan": faltan,
            "checklist_iniciado": iniciado,
            "checklist_faltantes": faltantes,
            "ultima_comunicacion": aggregations.ultima_comunicacion(pedidos_map.get(entidad.id, [])),
            "monto": float(entidad.monto) if entidad.monto is not None else None,
            "expediente": entidad.expediente,
        }
        return {"departamento": entidad.departamento, "nombre_localidad": nombre, "programa": prog}

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

    generado_para = ["vivienda"]
    lineas_privada = await fetch_privada_lineas()
    if lineas_privada:
        lineas.extend(lineas_privada)
        generado_para.append("privada")

    localidades = [
        ResumenLocalidad(**loc) for loc in aggregations.agrupar_por_localidad(lineas, geo)
    ]
    return ResumenTerritorialPayload(
        generado_para_areas=generado_para,
        total_localidades=len(localidades),
        total_programas=sum(len(loc.programas) for loc in localidades),
        localidades=localidades,
    )


# ── Cliente del API Gateway para las líneas de Privada ───────────────────────

def _mint_id_token(audience: str) -> str | None:
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token

        return id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    except Exception as exc:  # noqa: BLE001 — sin credenciales (local/test) es esperable
        logger.warning("resumen_territorial: no se pudo mintear ID token para Privada: %s", exc)
        return None


async def fetch_privada_lineas() -> list[dict]:
    """Trae las gestiones de la Secretaría Privada, agregadas por localidad, vía
    API Gateway. Tolerante: cualquier fallo → `[]` (el snapshot se guarda sólo
    con las líneas de Vivienda).

    NOTA: el contrato exacto de `/api/v1/privada/gestiones/resumen-territorial`
    no está en este repo (svc-privada es externo) — `_map_privada_payload`
    acepta varias formas plausibles y devuelve `[]` si no reconoce ninguna.
    Spec §3.3.
    """
    url = settings.gateway_base_url.rstrip("/") + settings.privada_resumen_path
    try:
        token = _mint_id_token(settings.privada_gateway_audience or settings.gateway_base_url)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return _map_privada_payload(resp.json())
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño
        logger.warning("resumen_territorial: fetch de Privada falló (%s): %s", url, exc)
        return []


def _map_privada_payload(data) -> list[dict]:
    if isinstance(data, dict):
        rows = data.get("localidades") or data.get("items") or data.get("data") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    lineas: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        loc = r.get("localidad") or r.get("nombre")
        if not loc:
            continue
        dep = r.get("departamento") or r.get("depto")
        por_estado_raw = r.get("por_estado") or r.get("estados") or {}
        por_estado = (
            {str(k): int(v) for k, v in por_estado_raw.items()}
            if isinstance(por_estado_raw, dict)
            else {}
        )
        total = r.get("total")
        if total is None:
            total = sum(por_estado.values()) if por_estado else int(r.get("cantidad", 0) or 0)
        meta = (
            aggregations.resumen_privada_estado(por_estado)
            if por_estado
            else dict(aggregations.SIN_ESTADO)
        )
        if por_estado:
            detalle = aggregations.detalle_privada(por_estado)
        elif total:
            detalle = aggregations._plural_gestiones(int(total))
        else:
            detalle = None
        ult = r.get("ultima_fecha") or r.get("fecha_ultima_actividad") or r.get("fecha_estado")
        prog = {
            "area": "privada",
            "programa": "gestiones",
            "programa_label": aggregations.PROGRAMA_LABEL["gestiones"],
            "entidad_id": None,
            "detalle": detalle,
            "estado_general_id": None,
            "estado_general_label": meta["label"],
            "estado_general_bg": meta["bg"],
            "estado_general_text_color": meta["text_color"],
            "subestados": None,
            "checklist_total": 0,
            "checklist_faltan": 0,
            "checklist_iniciado": False,
            "checklist_faltantes": [],
            "ultima_comunicacion": (
                {"fecha": ult, "texto": None, "area": "privada", "autor": None} if ult else None
            ),
            "monto": None,
            "expediente": None,
            "privada_conteos": {"por_estado": por_estado, "total": int(total or 0)},
        }
        lineas.append({"departamento": dep, "nombre_localidad": loc, "programa": prog})
    return lineas


# ── Snapshot ─────────────────────────────────────────────────────────────────

async def get_last_snapshot(db: AsyncSession) -> ResumenTerritorialSnapshot | None:
    result = await db.execute(
        select(ResumenTerritorialSnapshot)
        .order_by(ResumenTerritorialSnapshot.computed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def actualizar_resumen(db: AsyncSession, actor: AuthUser) -> ResumenTerritorialSnapshot:
    t0 = time.monotonic()
    payload = await compute_resumen_territorial(db)
    duracion_ms = int((time.monotonic() - t0) * 1000)

    snapshot = ResumenTerritorialSnapshot(
        payload=payload.model_dump(mode="json"),
        computed_at=datetime.now(timezone.utc),
        computed_by=actor.email,
        duracion_ms=duracion_ms,
    )
    db.add(snapshot)
    await db.flush()
    await log_audit(
        db,
        actor=actor,
        action="ACTUALIZAR_RESUMEN_TERRITORIAL",
        resource_type="resumen_territorial",
        resource_id="resumen_territorial",
        payload={
            "total_localidades": payload.total_localidades,
            "total_programas": payload.total_programas,
            "generado_para_areas": payload.generado_para_areas,
            "duracion_ms": duracion_ms,
        },
    )
    await db.refresh(snapshot)
    return snapshot


# ── Visibilidad ──────────────────────────────────────────────────────────────

def _enmascarar_comunicacion(prog, secs: set[str]):
    uc = prog.ultima_comunicacion
    if uc is None or uc.texto is None or "supervision" in secs:
        return prog
    area = (uc.area or "").lower()
    if area == "supervision" or (area == "infraestructura" and "infraestructura" not in secs):
        return prog.model_copy(update={"ultima_comunicacion": uc.model_copy(update={"texto": None})})
    return prog


def filtrar_por_visibilidad(
    payload: ResumenTerritorialPayload, *, rol: str, secretarias: list[str]
) -> ResumenTerritorialPayload:
    """Filtra el payload según el usuario. `Admin`/`Autoridad` ven todo. El resto
    ve sólo las líneas cuya `area` está en sus secretarías, y con el `texto` de
    comunicaciones de infraestructura/supervisión enmascarado. Spec §7.2."""
    if rol in _VER_TODO:
        return payload

    secs = set(secretarias or [])
    localidades = []
    for loc in payload.localidades:
        progs = [_enmascarar_comunicacion(p, secs) for p in loc.programas if p.area in secs]
        if progs:
            localidades.append(loc.model_copy(update={"programas": progs}))

    return ResumenTerritorialPayload(
        generado_para_areas=[a for a in payload.generado_para_areas if a in secs],
        total_localidades=len(localidades),
        total_programas=sum(len(loc.programas) for loc in localidades),
        localidades=localidades,
    )
