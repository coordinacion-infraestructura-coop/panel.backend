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
from app.checklist_tecnico import estado_tecnico
from app.config import settings
from app.resumen_territorial import aggregations
from app.resumen_territorial import lineas as lineas_mod
from app.resumen_territorial.models import ResumenTerritorialSnapshot
from app.resumen_territorial.schemas import ResumenLocalidad, ResumenTerritorialPayload

logger = logging.getLogger(__name__)

VER_TODO = ("Admin", "Autoridad")
# Únicos roles que reciben `ficha_gobierno` (datos institucionales de
# Gobierno: electores, masa salarial, intendente, partido, contacto, etc.).
# Lista propia, separada de `VER_TODO` a propósito: sumar un rol a "ver todas
# las áreas" no debe abrirle estos datos por arrastre
# (spec-datos-externos-fase1-nomenclador-demografia.md §7.1).
_ROLES_FICHA_GOBIERNO = ("Admin", "Autoridad")


# ── Cómputo ──────────────────────────────────────────────────────────────────

async def compute_resumen_territorial(db: AsyncSession) -> ResumenTerritorialPayload:
    geo = await lineas_mod.geo_rows(db)
    lineas = await lineas_mod.lineas_vivienda(db)

    generado_para = ["vivienda"]
    lineas_privada = await fetch_privada_lineas()
    if lineas_privada:
        lineas.extend(lineas_privada)
        generado_para.append("privada")

    lineas_gasifera = await fetch_gasifera_lineas()
    if lineas_gasifera:
        lineas.extend(lineas_gasifera)
        generado_para.append("gasifera")

    lineas_atp = await fetch_atp_lineas()
    if lineas_atp:
        lineas.extend(lineas_atp)
        generado_para.append("gralgob")

    # Quinta fuente (ADR-025): no produce líneas de "programa" — es
    # enriquecimiento (población/transferencias) que se mergea por id_geo
    # sobre cada localidad ya agrupada, no un ítem más de `lineas`.
    datos_externos_por_id_geo = {
        row["id_geo"]: row for row in await fetch_datos_externos_lineas()
    }
    if datos_externos_por_id_geo:
        generado_para.append("datos_externos")
    zonas_rurales = aggregations.normalizar_zonas_rurales(await fetch_zonas_rurales(), geo)

    grupos = aggregations.agrupar_por_localidad(lineas, geo)
    localidades = [
        ResumenLocalidad(**aggregations.enriquecer_con_datos_externos(g, datos_externos_por_id_geo))
        for g in grupos
    ]
    return ResumenTerritorialPayload(
        generado_para_areas=generado_para,
        total_localidades=len(localidades),
        total_programas=sum(len(loc.programas) for loc in localidades),
        localidades=localidades,
        total_localidades_por_departamento=aggregations.contar_localidades_por_departamento(
            geo, set(datos_externos_por_id_geo.keys())
        ),
        zonas_rurales=zonas_rurales,
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
    if not settings.privada_fetch_enabled:
        # Privada la federa el frontend con el token del usuario (spec §3.3, plan B).
        return []

    if settings.svc_privada_internal_url:
        # E5a / ADR-016: endpoint IAM-only de svc-privada, ID token dirigido a esa URL.
        base = settings.svc_privada_internal_url.rstrip("/")
        url = base + settings.privada_rollup_internal_path
        audience = base
    else:
        # camino viejo (gateway) — svc-privada lo rechaza; efectivamente desactivado.
        url = settings.gateway_base_url.rstrip("/") + settings.privada_resumen_path
        audience = settings.privada_gateway_audience or settings.gcp_project_id
    try:
        token = _mint_id_token(audience)
        if not token:
            logger.warning(
                "resumen_territorial: se llama a Privada SIN ID token (mint falló, audience=%s)",
                audience,
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.warning(
                "resumen_territorial: Privada respondió %s. url=%s aud=%s token_minteado=%s "
                "body[:1000]=%s",
                resp.status_code,
                url,
                audience,
                bool(token),
                (resp.text or "")[:1000],
            )
            return []

        lineas = _map_privada_payload(resp.json())
        if not lineas:
            logger.warning(
                "resumen_territorial: fetch de Privada OK (200) pero 0 líneas reconocidas. "
                "body[:1500]=%s",
                (resp.text or "")[:1500],
            )
        else:
            logger.info("resumen_territorial: Privada devolvió %d líneas por localidad", len(lineas))
        return lineas
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño
        logger.warning("resumen_territorial: fetch de Privada falló (%s): %r", url, exc)
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
        if not por_estado_raw and ("abiertas" in r or "finalizadas" in r):
            # forma del `rollup-territorial` interno (E5a): no trae desglose por
            # estado, pero sí los conteos abiertas/finalizadas → sintetizamos lo
            # justo para `resumen_privada_estado`.
            por_estado_raw = {}
            if r.get("abiertas"):
                por_estado_raw["EN CURSO"] = r["abiertas"]
            if r.get("finalizadas"):
                por_estado_raw["FINALIZADA"] = r["finalizadas"]
        por_estado = (
            {str(k): int(v) for k, v in por_estado_raw.items()}
            if isinstance(por_estado_raw, dict)
            else {}
        )
        total = r.get("total")
        if total is None:
            total = r.get("total_gestiones")
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
        ult = (
            r.get("ultima_fecha")
            or r.get("fecha_ultima_actividad")
            or r.get("fecha_estado")
            or r.get("fecha_estado_max")
        )
        # `ultima_comunicacion.fecha` es un `date` en el schema — el rollup interno
        # trae un timestamp ISO completo; truncar a YYYY-MM-DD (igual que el merge
        # client-side de `privadaGestiones.ts`).
        if isinstance(ult, str) and len(ult) > 10:
            ult = ult[:10]
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
        lineas.append({
            "departamento": dep, "nombre_localidad": loc,
            "id_geo": r.get("id_geo"), "programa": prog,
        })
    return lineas


# ── Cliente del endpoint interno de svc-gasifera (ADR-017) ──────────────────

async def fetch_gasifera_lineas() -> list[dict]:
    """Trae las acciones territoriales de gas, agregadas por localidad, del
    endpoint interno IAM-only de svc-gasifera. Tolerante: cualquier fallo →
    `[]` (el snapshot se guarda igual con lo que sí llegó) — mismo criterio
    que `fetch_privada_lineas` (ADR-016). Spec: ADR-017."""
    if not settings.gasifera_fetch_enabled or not settings.svc_gasifera_internal_url:
        return []

    base = settings.svc_gasifera_internal_url.rstrip("/")
    url = base + settings.gasifera_rollup_internal_path
    audience = base
    try:
        token = _mint_id_token(audience)
        if not token:
            logger.warning(
                "resumen_territorial: se llama a Gasífera SIN ID token (mint falló, audience=%s)",
                audience,
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.warning(
                "resumen_territorial: Gasífera respondió %s. url=%s aud=%s token_minteado=%s "
                "body[:1000]=%s",
                resp.status_code, url, audience, bool(token), (resp.text or "")[:1000],
            )
            return []

        lineas = _map_gasifera_payload(resp.json())
        logger.info("resumen_territorial: Gasífera devolvió %d líneas por localidad", len(lineas))
        return lineas
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño
        logger.warning("resumen_territorial: fetch de Gasífera falló (%s): %r", url, exc)
        return []


def _map_gasifera_payload(data) -> list[dict]:
    """A diferencia de `_map_privada_payload` (contrato externo no versionado
    en este repo), acá el contrato lo controlamos nosotros mismos
    (`gas_pit_rollup.rollup_territorial`) — mapeo directo, sin heurísticas."""
    if not isinstance(data, list):
        return []

    lineas: list[dict] = []
    for r in data:
        if not isinstance(r, dict):
            continue
        loc = r.get("localidad")
        if not loc:
            continue
        por_estado = {}
        if r.get("cumplidas"):
            por_estado["CUMPLIDO"] = r["cumplidas"]
        if r.get("en_curso"):
            por_estado["EN CURSO"] = r["en_curso"]
        meta = (
            aggregations.resumen_gasifera_estado(por_estado)
            if por_estado
            else dict(aggregations.SIN_ESTADO)
        )
        detalle = (
            aggregations.detalle_gasifera(por_estado)
            if por_estado
            else None
        )
        monto = r.get("monto_usd_sum")
        prog = {
            "area": "gasifera",
            "programa": "acciones_territorio",
            "programa_label": aggregations.PROGRAMA_LABEL["acciones_territorio"],
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
                {"fecha": r["fecha_max"], "texto": None, "area": "gasifera", "autor": None}
                if r.get("fecha_max") else None
            ),
            "monto": float(monto) if monto is not None else None,
            "expediente": None,
        }
        lineas.append({
            "departamento": r.get("departamento"), "nombre_localidad": loc,
            "id_geo": r.get("id_geo"), "programa": prog,
        })
    return lineas


# ── Cliente del endpoint interno de svc-gralgob / ATP ────────────────────────

async def fetch_atp_lineas() -> list[dict]:
    """Trae los compromisos ATP, agregados por localidad, del endpoint interno
    IAM-only de svc-gralgob. Tolerante: cualquier fallo → `[]` (el snapshot se
    guarda igual con lo que sí llegó) — mismo criterio que `fetch_privada_lineas`
    (ADR-016) y `fetch_gasifera_lineas` (ADR-021)."""
    if not settings.atp_fetch_enabled or not settings.svc_gralgob_internal_url:
        return []

    base = settings.svc_gralgob_internal_url.rstrip("/")
    url = base + settings.atp_rollup_internal_path
    audience = base
    try:
        token = _mint_id_token(audience)
        if not token:
            logger.warning(
                "resumen_territorial: se llama a ATP/gralgob SIN ID token (mint falló, audience=%s)",
                audience,
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.warning(
                "resumen_territorial: ATP/gralgob respondió %s. url=%s aud=%s token_minteado=%s "
                "body[:1000]=%s",
                resp.status_code, url, audience, bool(token), (resp.text or "")[:1000],
            )
            return []

        lineas = _map_atp_payload(resp.json())
        logger.info("resumen_territorial: ATP/gralgob devolvió %d líneas por localidad", len(lineas))
        return lineas
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño
        logger.warning("resumen_territorial: fetch de ATP/gralgob falló (%s): %r", url, exc)
        return []


def _map_atp_payload(data) -> list[dict]:
    """Contrato controlado por nosotros mismos (`atp.rollup.rollup_territorial`
    en svc-gralgob) — mapeo directo, sin heurísticas, mismo criterio que
    `_map_gasifera_payload`."""
    if not isinstance(data, list):
        return []

    lineas: list[dict] = []
    for r in data:
        if not isinstance(r, dict):
            continue
        loc = r.get("localidad")
        if not loc:
            continue
        monto_total = r.get("monto_total_sum")
        entregado = r.get("entregado_sum") or 0.0
        meta = aggregations.resumen_atp_estado(monto_total, entregado)
        detalle = aggregations.detalle_atp(r.get("total_compromisos", 0), r.get("derivados", 0))
        prog = {
            "area": "gralgob",
            "programa": "atp",
            "programa_label": aggregations.PROGRAMA_LABEL["atp"],
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
                {"fecha": r["fecha_max"], "texto": None, "area": "gralgob", "autor": None}
                if r.get("fecha_max") else None
            ),
            "monto": float(monto_total) if monto_total is not None else None,
            "monto_entregado": float(entregado),
            "expediente": None,
        }
        lineas.append({
            "departamento": r.get("departamento"), "nombre_localidad": loc,
            "id_geo": r.get("id_geo"), "programa": prog,
        })
    return lineas


# ── Cliente del endpoint interno de svc-datos-externos (ADR-025) ────────────

async def fetch_datos_externos_lineas() -> list[dict]:
    """Trae población/viviendas (Censo 2022) y transferencias del último
    período cargado, por `id_geo`, del endpoint interno IAM-only de
    svc-datos-externos. Tolerante: cualquier fallo → `[]` (mismo criterio que
    `fetch_gasifera_lineas`/`fetch_atp_lineas`, ADR-016/021/022).

    A diferencia de esas 3 fuentes, esto NO produce líneas de "programa": es
    enriquecimiento que se mergea directo sobre cada `ResumenLocalidad` por
    `id_geo` (ver `aggregations.enriquecer_con_datos_externos`) — por eso el
    resultado se indexa por `id_geo` en vez de sumarse a `lineas`."""
    if not settings.datos_externos_fetch_enabled or not settings.svc_datos_externos_internal_url:
        return []

    base = settings.svc_datos_externos_internal_url.rstrip("/")
    url = base + settings.datos_externos_rollup_internal_path
    audience = base
    try:
        token = _mint_id_token(audience)
        if not token:
            logger.warning(
                "resumen_territorial: se llama a datos-externos SIN ID token (mint falló, audience=%s)",
                audience,
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.warning(
                "resumen_territorial: datos-externos respondió %s. url=%s aud=%s token_minteado=%s "
                "body[:1000]=%s",
                resp.status_code, url, audience, bool(token), (resp.text or "")[:1000],
            )
            return []

        data = resp.json()
        if not isinstance(data, list):
            return []
        lineas = [r for r in data if isinstance(r, dict) and r.get("id_geo")]
        logger.info("resumen_territorial: datos-externos devolvió %d localidades con id_geo", len(lineas))
        return lineas
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño
        logger.warning("resumen_territorial: fetch de datos-externos falló (%s): %r", url, exc)
        return []


async def fetch_zonas_rurales() -> list[dict]:
    """Población de zona rural por departamento, del endpoint interno IAM-only
    de svc-datos-externos. Misma tolerancia que `fetch_datos_externos_lineas`:
    cualquier fallo → `[]`."""
    if not settings.datos_externos_fetch_enabled or not settings.svc_datos_externos_internal_url:
        return []

    base = settings.svc_datos_externos_internal_url.rstrip("/")
    url = base + settings.datos_externos_zonas_rurales_internal_path
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning("resumen_territorial: zonas-rurales respondió %s. url=%s", resp.status_code, url)
            return []
        data = resp.json()
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño
        logger.warning("resumen_territorial: fetch de zonas-rurales falló (%s): %r", url, exc)
        return []


# ── Snapshot ─────────────────────────────────────────────────────────────────

async def avances_vivienda(db: AsyncSession, localidades: list[dict]) -> list[int]:
    """Avance vigente (%) de cada obra de Vivienda del payload que tenga al menos una
    medición — insumo de `avance_obra_promedio` en los KPIs (spec-vivienda-tablero-analitico §4.3).
    El avance no viaja en el payload del snapshot a propósito (ADR-030)."""
    ids = {
        (aggregations.PROGRAMA_A_CHECKLIST[p["programa"]], p["entidad_id"])
        for loc in localidades
        for p in loc.get("programas", [])
        if p.get("area") == "vivienda" and p.get("programa") in aggregations.PROGRAMA_A_CHECKLIST
    }
    avances: list[int] = []
    for cod in ("cc", "ch", "ml"):
        for entidad_id, obra in (await estado_tecnico.avance_por_entidad(db, cod, {})).items():
            if (cod, entidad_id) in ids and obra["avance_obra_pct"] is not None:
                avances.append(obra["avance_obra_pct"])
    return avances


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

    computed_at = datetime.now(timezone.utc)
    payload_json = payload.model_dump(mode="json")
    snapshot = ResumenTerritorialSnapshot(
        payload=payload_json,
        computed_at=computed_at,
        computed_by=actor.email,
        duracion_ms=duracion_ms,
        kpis=aggregations.kpis_por_area(
            payload_json["localidades"],
            aggregations.dia_ar(computed_at),
            {"vivienda": await avances_vivienda(db, payload_json["localidades"])},
        ),
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

def comunicacion_visible(area: str | None, secs: set[str]) -> bool:
    """¿Un usuario (no Admin/Autoridad) con secretarías `secs` puede leer el texto de una
    comunicación del área `area`? Las de supervisión sólo las lee supervisión; las de
    infraestructura, infraestructura o supervisión. También la usa `app/tablero_analitico`."""
    if "supervision" in secs:
        return True
    area = (area or "").lower()
    return not (area == "supervision" or (area == "infraestructura" and "infraestructura" not in secs))


def _enmascarar_comunicacion(prog, secs: set[str]):
    uc = prog.ultima_comunicacion
    if uc is None or uc.texto is None or comunicacion_visible(uc.area, secs):
        return prog
    return prog.model_copy(update={"ultima_comunicacion": uc.model_copy(update={"texto": None})})


def filtrar_por_visibilidad(
    payload: ResumenTerritorialPayload, *, rol: str, secretarias: list[str]
) -> ResumenTerritorialPayload:
    """Filtra el payload según el usuario. `Admin`/`Autoridad` ven todo. El resto
    ve sólo las líneas cuya `area` está en sus secretarías, y con el `texto` de
    comunicaciones de infraestructura/supervisión enmascarado. Spec §7.2.

    `ficha_gobierno` tiene su propia regla, más estricta: parte de "no se
    muestra" y sólo se conserva para `_ROLES_FICHA_GOBIERNO`. Se aplica antes
    que cualquier otra rama, para que ningún camino la deje pasar."""
    if rol not in _ROLES_FICHA_GOBIERNO:
        payload = payload.model_copy(update={
            "localidades": [
                loc if loc.ficha_gobierno is None else loc.model_copy(update={"ficha_gobierno": None})
                for loc in payload.localidades
            ]
        })

    if rol in VER_TODO:
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
        # Metadata pública del padrón (denominador de cobertura), no un "programa"
        # de ninguna secretaría — se preserva igual para todos los roles, mismo
        # criterio que el enriquecimiento de datos-externos (población/transferencias).
        total_localidades_por_departamento=payload.total_localidades_por_departamento,
        zonas_rurales=payload.zonas_rurales,
    )
