"""Asignación manual de localidades sin resolver: un Admin vincula a una fila
del padrón (o marca "confirmado sin vínculo") lo que `resolver_lote` dejó en
`viv_geo_pendientes`, sin pasar por una migración.

Ver docs/files/spec-geo-asignacion-manual-localidades.md.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.config import settings
from app.cordoba_hogar.models import LocalidadCordobaHogar
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.geo.matching import normalize_departamento, normalize_name
from app.geo.models import GeoAliasManual, GeoLocalidad, GeoPendiente
from app.geo.schemas import ResolverPendienteIn
from app.mi_lugar.models import ProyectoML
from app.resumen_territorial import service as resumen_service

logger = logging.getLogger(__name__)

# programa → (modelo, atributo que guarda el nombre de la localidad)
_PROGRAMAS = {
    "cordon_cuneta": (MunicipioCordonCuneta, "municipio"),
    "cordoba_hogar": (LocalidadCordobaHogar, "localidad"),
    "mi_lugar": (ProyectoML, "localidad_nombre"),
}
# En estos dos, una localidad = un registro (409 al cargar un duplicado).
_PROGRAMAS_UNICOS = ("cordon_cuneta", "cordoba_hogar")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _sin_vinculo(db: AsyncSession) -> list[tuple[str, object, str]]:
    """Registros activos de CC/CH/ML sin `localidad_id`: `(programa, fila, atributo_nombre)`."""
    salida = []
    for programa, (modelo, attr) in _PROGRAMAS.items():
        filas = (
            await db.execute(
                select(modelo).where(modelo.deleted_at.is_(None), modelo.localidad_id.is_(None))
            )
        ).scalars().all()
        salida += [(programa, f, attr) for f in filas]
    return salida


def _coincide(fila, attr: str, texto: str, departamento: str) -> bool:
    """`departamento == ""` = sin acotar (alias global)."""
    if normalize_name(getattr(fila, attr)) != texto:
        return False
    return not departamento or normalize_departamento(fila.departamento) == departamento


def _alias_out(a: GeoAliasManual, por_id: dict[str, GeoLocalidad]) -> dict:
    geo = por_id.get(a.id_geo) if a.id_geo else None
    return {
        "id": a.id,
        "texto_original": a.texto_original,
        "departamento_normalizado": a.departamento_normalizado,
        "id_geo": a.id_geo,
        "localidad_oficial": geo.localidad if geo else None,
        "departamento_oficial": geo.departamento if geo else None,
        "motivo": a.motivo,
        "origen": a.origen,
        "created_at": a.created_at,
        "created_by": a.created_by,
    }


async def _padron_por_id(db: AsyncSession) -> dict[str, GeoLocalidad]:
    return {g.id_geo: g for g in (await db.execute(select(GeoLocalidad))).scalars().all()}


# ── Lectura ──────────────────────────────────────────────────────────────────

async def listar_pendientes(
    db: AsyncSession, *, estado: str = "pendiente", origen: str | None = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    filtro = [GeoPendiente.estado == estado]
    if origen:
        filtro.append(GeoPendiente.origen == origen)
    total = (
        await db.execute(select(func.count()).select_from(GeoPendiente).where(*filtro))
    ).scalar_one()
    filas = (
        await db.execute(
            select(GeoPendiente).where(*filtro)
            .order_by(GeoPendiente.ultima_vez.desc(), GeoPendiente.localidad_original)
            .limit(limit).offset(offset)
        )
    ).scalars().all()

    alias_ids = {p.alias_id for p in filas if p.alias_id}
    alias = {}
    if alias_ids:
        alias = {
            a.id: a
            for a in (
                await db.execute(select(GeoAliasManual).where(GeoAliasManual.id.in_(alias_ids)))
            ).scalars().all()
        }
    por_id = await _padron_por_id(db) if alias else {}
    # CC/CH/ML sólo pasan por el resolver al guardar un registro: su cantidad
    # se cuenta en vivo, no sale de la última corrida.
    sin_vinculo = await _sin_vinculo(db) if any(p.origen in _PROGRAMAS for p in filas) else []

    items = []
    for p in filas:
        cantidad = p.cantidad
        if p.origen in _PROGRAMAS and p.estado == "pendiente":
            cantidad = sum(
                1 for programa, fila, attr in sin_vinculo
                if programa == p.origen
                and _coincide(fila, attr, p.texto_normalizado, p.departamento_normalizado)
            )
        a = alias.get(p.alias_id) if p.alias_id else None
        items.append({
            "id": p.id,
            "origen": p.origen,
            "departamento": p.departamento_original,
            "localidad": p.localidad_original,
            "cantidad": cantidad,
            "primera_vez": p.primera_vez,
            "ultima_vez": p.ultima_vez,
            "estado": p.estado,
            "resuelta_at": p.resuelta_at,
            "resuelta_by": p.resuelta_by,
            "alias": _alias_out(a, por_id) if a else None,
        })
    return {"items": items, "total": int(total)}


async def listar_alias(db: AsyncSession, *, limit: int = 50, offset: int = 0) -> dict:
    vigente = GeoAliasManual.deleted_at.is_(None)
    total = (
        await db.execute(select(func.count()).select_from(GeoAliasManual).where(vigente))
    ).scalar_one()
    filas = (
        await db.execute(
            select(GeoAliasManual).where(vigente)
            .order_by(GeoAliasManual.texto_original).limit(limit).offset(offset)
        )
    ).scalars().all()
    por_id = await _padron_por_id(db)
    return {"items": [_alias_out(a, por_id) for a in filas], "total": int(total)}


# ── Escritura ────────────────────────────────────────────────────────────────

async def _get_pendiente(db: AsyncSession, pendiente_id: str) -> GeoPendiente:
    p = (
        await db.execute(select(GeoPendiente).where(GeoPendiente.id == pendiente_id))
    ).scalar_one_or_none()
    if p is None:
        raise _error(status.HTTP_404_NOT_FOUND, "PENDIENTE_NO_ENCONTRADO", "No existe ese pendiente")
    return p


def _mint_id_token(audience: str) -> str | None:
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token

        return id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    except Exception as exc:  # noqa: BLE001 — sin credenciales (local/test) es esperable
        logger.warning("geo.asignacion: no se pudo mintear ID token para Privada: %s", exc)
        return None


async def _normalizar_privada() -> str:
    """Le pide a svc-privada que repunte sus gestiones contra el padrón (endpoint
    IAM-only, idempotente). Best-effort: `"aplicado"` / `"fallo"` / `"no_aplica"`."""
    if not settings.svc_privada_internal_url:
        return "no_aplica"
    base = settings.svc_privada_internal_url.rstrip("/")
    url = base + settings.privada_normalizar_internal_path
    try:
        token = _mint_id_token(base)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, params={"dry_run": "false"}, headers=headers)
        if resp.status_code != 200:
            logger.warning("geo.asignacion: %s respondió %s", url, resp.status_code)
            return "fallo"
        return "aplicado"
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo.asignacion: fallo llamando a %s: %r", url, exc)
        return "fallo"


async def _recalcular_resumen(db: AsyncSession, actor: AuthUser) -> str:
    try:
        await resumen_service.actualizar_resumen(db, actor)
        await db.commit()
        return "aplicado"
    except Exception:  # noqa: BLE001
        logger.exception("geo.asignacion: no se pudo recalcular el Resumen Territorial")
        await db.rollback()
        return "fallo"


async def resolver_pendiente(
    db: AsyncSession, actor: AuthUser, pendiente_id: str, data: ResolverPendienteIn
) -> dict:
    """Crea el alias que resuelve el pendiente (`id_geo` = fila del padrón, o
    `None` = "confirmado sin vínculo") y propaga el vínculo a CC/CH/ML. Con
    `dry_run` devuelve el impacto sin escribir."""
    pendiente = await _get_pendiente(db, pendiente_id)
    if pendiente.estado == "resuelta":
        raise _error(status.HTTP_409_CONFLICT, "PENDIENTE_YA_RESUELTO", "Ese pendiente ya está resuelto")

    geo = None
    if data.id_geo is not None:
        geo = (
            await db.execute(select(GeoLocalidad).where(GeoLocalidad.id_geo == data.id_geo))
        ).scalar_one_or_none()
        if geo is None or not geo.activo:
            raise _error(
                status.HTTP_400_BAD_REQUEST, "LOCALIDAD_INVALIDA",
                "La localidad elegida no es una fila activa del padrón",
            )

    texto = pendiente.texto_normalizado
    departamento = pendiente.departamento_normalizado if data.alcance == "departamento" else ""
    existente = (
        await db.execute(
            select(GeoAliasManual.id).where(
                GeoAliasManual.texto_normalizado == texto,
                GeoAliasManual.departamento_normalizado == departamento,
                GeoAliasManual.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise _error(
            status.HTTP_409_CONFLICT, "ALIAS_EXISTENTE",
            "Ya hay un vínculo manual para ese texto con ese alcance",
        )

    afectados = [
        (programa, fila, attr) for programa, fila, attr in await _sin_vinculo(db)
        if _coincide(fila, attr, texto, departamento)
    ]
    registros = [
        {
            "programa": programa,
            "id": fila.id,
            "nombre_actual": getattr(fila, attr),
            "departamento_actual": fila.departamento,
            "nombre_oficial": geo.localidad if geo else None,
            "departamento_oficial": geo.departamento if geo else None,
        }
        for programa, fila, attr in afectados
    ]

    duplicados = []
    if geo is not None:
        for programa in _PROGRAMAS_UNICOS:
            modelo, _ = _PROGRAMAS[programa]
            ya_vinculados = (
                await db.execute(
                    select(func.count()).select_from(modelo).where(
                        modelo.deleted_at.is_(None), modelo.localidad_id == geo.id_geo
                    )
                )
            ).scalar_one()
            cantidad = int(ya_vinculados) + sum(1 for p, _, _ in afectados if p == programa)
            if cantidad > 1 and any(p == programa for p, _, _ in afectados):
                duplicados.append({"programa": programa, "cantidad": cantidad})

    filtro_pendientes = [GeoPendiente.estado != "resuelta", GeoPendiente.texto_normalizado == texto]
    if departamento:
        filtro_pendientes.append(GeoPendiente.departamento_normalizado == departamento)
    pendientes = (await db.execute(select(GeoPendiente).where(*filtro_pendientes))).scalars().all()

    avisos = [
        f"Quedan {d['cantidad']} registros activos de {d['programa']} con la misma localidad: "
        "la fusión es manual, desde el panel del programa."
        for d in duplicados
    ]
    salida = {
        "dry_run": data.dry_run,
        "id_geo": geo.id_geo if geo else None,
        "localidad_oficial": geo.localidad if geo else None,
        "departamento_oficial": geo.departamento if geo else None,
        "registros": registros,
        "duplicados": duplicados,
        "pendientes_resueltos": len(pendientes),
        "propagacion": {},
        "avisos": avisos,
    }
    if data.dry_run:
        return salida

    now = _now()
    propagacion = []
    for programa, fila, attr in afectados:
        antes = {
            "nombre": getattr(fila, attr), "departamento": fila.departamento,
            "localidad_id": fila.localidad_id, "match_tipo": fila.localidad_match_tipo,
        }
        fila.localidad_match_tipo = "manual"
        if geo is not None:
            # Con vínculo se guarda el nombre del padrón oficial (ADR-026).
            fila.localidad_id = geo.id_geo
            setattr(fila, attr, geo.localidad)
            fila.departamento = geo.departamento
        fila.updated_by = actor.email
        despues = {
            "nombre": getattr(fila, attr), "departamento": fila.departamento,
            "localidad_id": fila.localidad_id, "match_tipo": fila.localidad_match_tipo,
        }
        propagacion.append({"programa": programa, "id": fila.id, "antes": antes, "despues": despues})

    alias = GeoAliasManual(
        texto_normalizado=texto,
        departamento_normalizado=departamento,
        texto_original=pendiente.localidad_original,
        id_geo=geo.id_geo if geo else None,
        motivo=data.motivo.strip(),
        origen=pendiente.origen,
        created_at=now,
        created_by=actor.email,
        propagacion=json.dumps(propagacion, ensure_ascii=False),
    )
    db.add(alias)
    await db.flush()

    for p in pendientes:
        p.estado, p.alias_id, p.resuelta_at, p.resuelta_by = "resuelta", alias.id, now, actor.email
    await db.flush()

    await log_audit(
        db, actor=actor, action="CREATE", resource_type="geo_alias_manual", resource_id=alias.id,
        payload={
            "texto": pendiente.localidad_original, "departamento": departamento,
            "id_geo": alias.id_geo, "motivo": alias.motivo, "pendiente_id": pendiente.id,
            "registros_propagados": len(propagacion),
        },
    )
    for reg in propagacion:
        await log_audit(
            db, actor=actor, action="UPDATE", resource_type=reg["programa"], resource_id=reg["id"],
            payload={
                "motivo": "vínculo manual de localidad", "alias_id": alias.id,
                "antes": reg["antes"], "despues": reg["despues"],
            },
        )

    # Lo que sigue son llamadas best-effort a otros servicios: el vínculo tiene
    # que estar confirmado antes (svc-privada vuelve a consultar el resolver).
    await db.commit()

    if geo is None:
        salida["propagacion"] = {
            "gasifera": "no_aplica", "atp": "no_aplica", "datos_externos": "no_aplica",
            "privada": "no_aplica", "resumen_territorial": "no_aplica",
        }
        return salida

    privada = await _normalizar_privada()
    resumen = await _recalcular_resumen(db, actor)
    salida["propagacion"] = {
        "gasifera": "proximo_sync", "atp": "proximo_sync", "datos_externos": "proximo_sync",
        "privada": privada, "resumen_territorial": resumen,
    }
    avisos.append("Gasífera y ATP toman el vínculo en su próxima sincronización (hasta 1 hora).")
    if privada == "fallo":
        avisos.append(
            "No se pudo actualizar Privada: sus gestiones quedan sin repuntear hasta la próxima normalización."
        )
    if resumen == "fallo":
        avisos.append("No se pudo recalcular el Resumen Territorial: usá “Actualizar” en ese panel.")
    return salida


async def descartar_pendiente(db: AsyncSession, actor: AuthUser, pendiente_id: str) -> None:
    """Saca el pendiente de la lista sin crear un alias (ej. la fuente ya
    corrigió la grafía). Si vuelve a aparecer en una corrida, se reabre."""
    pendiente = await _get_pendiente(db, pendiente_id)
    if pendiente.estado != "pendiente":
        raise _error(status.HTTP_409_CONFLICT, "PENDIENTE_NO_ABIERTO", "Ese pendiente no está abierto")
    pendiente.estado, pendiente.resuelta_at, pendiente.resuelta_by = "descartada", _now(), actor.email
    await db.flush()
    await log_audit(
        db, actor=actor, action="DESCARTAR", resource_type="geo_pendiente", resource_id=pendiente.id,
        payload={
            "origen": pendiente.origen, "departamento": pendiente.departamento_original,
            "localidad": pendiente.localidad_original,
        },
    )


async def deshacer(db: AsyncSession, actor: AuthUser, pendiente_id: str) -> dict:
    """Da de baja el alias que resolvió el pendiente, reabre los pendientes que
    había cerrado y restaura los registros de CC/CH/ML a como estaban. Un
    registro editado después de la propagación no se toca."""
    pendiente = await _get_pendiente(db, pendiente_id)
    if pendiente.estado != "resuelta" or not pendiente.alias_id:
        raise _error(status.HTTP_409_CONFLICT, "PENDIENTE_NO_RESUELTO", "Ese pendiente no tiene un vínculo para deshacer")
    alias = (
        await db.execute(select(GeoAliasManual).where(GeoAliasManual.id == pendiente.alias_id))
    ).scalar_one()

    restaurados = omitidos = 0
    for reg in json.loads(alias.propagacion or "[]"):
        modelo, attr = _PROGRAMAS[reg["programa"]]
        fila = (await db.execute(select(modelo).where(modelo.id == reg["id"]))).scalar_one_or_none()
        despues, antes = reg["despues"], reg["antes"]
        actual = None if fila is None else {
            "nombre": getattr(fila, attr), "departamento": fila.departamento,
            "localidad_id": fila.localidad_id, "match_tipo": fila.localidad_match_tipo,
        }
        if fila is None or fila.deleted_at is not None or actual != despues:
            omitidos += 1
            continue
        setattr(fila, attr, antes["nombre"])
        fila.departamento = antes["departamento"]
        fila.localidad_id = antes["localidad_id"]
        fila.localidad_match_tipo = antes["match_tipo"]
        fila.updated_by = actor.email
        restaurados += 1
        await log_audit(
            db, actor=actor, action="UPDATE", resource_type=reg["programa"], resource_id=reg["id"],
            payload={
                "motivo": "se deshizo un vínculo manual de localidad", "alias_id": alias.id,
                "antes": despues, "despues": antes,
            },
        )

    now = _now()
    alias.deleted_at, alias.updated_at, alias.updated_by = now, now, actor.email
    reabiertos = (
        await db.execute(select(GeoPendiente).where(GeoPendiente.alias_id == alias.id))
    ).scalars().all()
    for p in reabiertos:
        p.estado, p.alias_id, p.resuelta_at, p.resuelta_by = "pendiente", None, None, None
    await db.flush()
    await log_audit(
        db, actor=actor, action="DELETE", resource_type="geo_alias_manual", resource_id=alias.id,
        payload={
            "texto": alias.texto_original, "departamento": alias.departamento_normalizado,
            "id_geo": alias.id_geo, "registros_restaurados": restaurados, "registros_omitidos": omitidos,
        },
    )
    await db.commit()

    avisos = []
    if omitidos:
        avisos.append(
            f"{omitidos} registro(s) de Vivienda no se restauraron porque se editaron después de vincularlos."
        )
    if alias.id_geo:
        avisos.append("Gasífera y ATP pierden el vínculo en su próxima sincronización (hasta 1 hora).")
        avisos.append(
            "Las gestiones de Privada que hayan tomado este vínculo no se revierten solas: "
            "hay que corregirlas desde el panel de Privada."
        )
        if await _recalcular_resumen(db, actor) == "fallo":
            avisos.append("No se pudo recalcular el Resumen Territorial: usá “Actualizar” en ese panel.")
    return {
        "registros_restaurados": restaurados,
        "registros_omitidos": omitidos,
        "pendientes_reabiertos": len(reabiertos),
        "avisos": avisos,
    }
