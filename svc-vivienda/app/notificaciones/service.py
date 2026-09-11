"""Notificaciones internas — queries inline, patrón panel-module (sin repository.py).

Feed global filtrado por visibilidad en la lectura (`Admin`/`Autoridad` ven todo; el
resto ve las globales + las de su rol/secretarías). El estado de lectura es por
usuario en `portal_notificacion_lecturas`.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.notificaciones.models import Notificacion, NotificacionLectura

_VER_TODO = ("Admin", "Autoridad")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _visible_clause(user: AuthUser):
    """Condición SQL de visibilidad de una notificación para `user`
    (siempre excluye las borradas)."""
    no_borrada = Notificacion.deleted_at.is_(None)
    if user.role in _VER_TODO:
        return no_borrada
    cond = [
        Notificacion.destino_tipo == "global",
        and_(Notificacion.destino_tipo == "rol", Notificacion.destino_valor == user.role),
    ]
    if user.secretarias:
        cond.append(
            and_(
                Notificacion.destino_tipo == "secretaria",
                Notificacion.destino_valor.in_(user.secretarias),
            )
        )
    return and_(no_borrada, or_(*cond))


def _leida_expr(email: str):
    """Subconsulta correlacionada: True si el usuario ya marcó la notificación como leída."""
    return (
        select(NotificacionLectura.notificacion_id)
        .where(
            NotificacionLectura.notificacion_id == Notificacion.id,
            NotificacionLectura.usuario_email == email,
        )
        .exists()
    )


async def listar(
    db: AsyncSession,
    user: AuthUser,
    *,
    solo_no_leidas: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    visible = _visible_clause(user)
    leida = _leida_expr(user.email)

    stmt = select(Notificacion, leida.label("leida")).where(visible)
    if solo_no_leidas:
        stmt = stmt.where(~leida)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    no_leidas = await contar_no_leidas(db, user)

    rows = (
        await db.execute(
            stmt.order_by(Notificacion.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()

    items = [
        {
            "id": n.id,
            "titulo": n.titulo,
            "mensaje": n.mensaje,
            "nivel": n.nivel,
            "origen": n.origen,
            "enlace": n.enlace,
            "destino_tipo": n.destino_tipo,
            "destino_valor": n.destino_valor,
            "created_at": n.created_at,
            "leida": bool(ya_leida),
        }
        for n, ya_leida in rows
    ]
    return {"items": items, "total": int(total), "no_leidas": int(no_leidas)}


async def contar_no_leidas(db: AsyncSession, user: AuthUser) -> int:
    visible = _visible_clause(user)
    q = (
        select(func.count())
        .select_from(Notificacion)
        .where(visible, ~_leida_expr(user.email))
    )
    return int((await db.execute(q)).scalar_one())


async def marcar_leida(db: AsyncSession, user: AuthUser, notif_id: str) -> None:
    visible = _visible_clause(user)
    existe = (
        await db.execute(select(Notificacion.id).where(visible, Notificacion.id == notif_id))
    ).scalar_one_or_none()
    if existe is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOTIFICACION_NO_ENCONTRADA", "message": "No existe o no es visible"},
        )
    ya = (
        await db.execute(
            select(NotificacionLectura).where(
                NotificacionLectura.notificacion_id == notif_id,
                NotificacionLectura.usuario_email == user.email,
            )
        )
    ).scalar_one_or_none()
    if ya is not None:
        return
    db.add(
        NotificacionLectura(
            notificacion_id=notif_id, usuario_email=user.email, leida_at=_now()
        )
    )
    await db.flush()
    await log_audit(
        db, actor=user, action="MARCAR_LEIDA", resource_type="notificacion",
        resource_id=notif_id, payload={},
    )


async def marcar_todas_leidas(db: AsyncSession, user: AuthUser) -> int:
    visible = _visible_clause(user)
    pendientes = (
        await db.execute(
            select(Notificacion.id).where(visible, ~_leida_expr(user.email))
        )
    ).scalars().all()
    if not pendientes:
        return 0
    now = _now()
    for nid in pendientes:
        db.add(NotificacionLectura(notificacion_id=nid, usuario_email=user.email, leida_at=now))
    await db.flush()
    await log_audit(
        db, actor=user, action="MARCAR_TODAS_LEIDAS", resource_type="notificacion",
        resource_id="*", payload={"cantidad": len(pendientes)},
    )
    return len(pendientes)


async def crear(db: AsyncSession, actor: AuthUser, data: dict) -> Notificacion:
    n = Notificacion(
        titulo=data["titulo"],
        mensaje=data["mensaje"],
        nivel=data.get("nivel") or "info",
        origen=data.get("origen") or "sistema",
        enlace=data.get("enlace"),
        destino_tipo=data.get("destino_tipo") or "global",
        destino_valor=data.get("destino_valor"),
        created_by=actor.email,
    )
    db.add(n)
    await db.flush()
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="notificacion",
        resource_id=n.id,
        payload={k: data.get(k) for k in ("nivel", "origen", "destino_tipo", "destino_valor")},
    )
    return n
