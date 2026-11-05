"""Conversaciones, preguntas, auditoría y feedback (spec §6.4)."""
from datetime import date, datetime, time, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agente import indicadores, llm
from app.auth import AuthUser
from app.config import settings
from app.conversaciones.models import Conversacion, Feedback, Interaccion, Mensaje


def _error(code: int, codigo: str, msg: str) -> HTTPException:
    return HTTPException(status_code=code, detail={"code": codigo, "message": msg})


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


async def listar(db: AsyncSession, user: AuthUser, limit: int, offset: int) -> dict:
    base = select(Conversacion).where(Conversacion.email == user.email, Conversacion.deleted_at.is_(None))
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    items = (await db.execute(base.order_by(Conversacion.updated_at.desc()).limit(limit).offset(offset))).scalars().all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def crear(db: AsyncSession, user: AuthUser, titulo: str | None) -> Conversacion:
    ahora = _ahora()
    c = Conversacion(email=user.email, titulo=titulo or "Nueva consulta", created_at=ahora, updated_at=ahora)
    db.add(c)
    await db.flush()
    return c


async def obtener(db: AsyncSession, user: AuthUser, conv_id: str) -> Conversacion:
    c = await db.get(Conversacion, conv_id)
    # Una conversación ajena se responde igual que una inexistente.
    if c is None or c.deleted_at is not None or c.email != user.email:
        raise _error(404, "CONVERSACION_NO_ENCONTRADA", "Conversación no encontrada")
    return c


async def mensajes(db: AsyncSession, conv_id: str) -> list[Mensaje]:
    return (await db.execute(
        select(Mensaje).where(Mensaje.conversacion_id == conv_id).order_by(Mensaje.created_at, Mensaje.rol.desc())
    )).scalars().all()


async def borrar(db: AsyncSession, user: AuthUser, conv_id: str) -> None:
    c = await obtener(db, user, conv_id)
    c.deleted_at = _ahora()


async def verificar_cuota(db: AsyncSession, user: AuthUser) -> None:
    inicio = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    usadas = (await db.execute(
        select(func.count()).select_from(Interaccion)
        .where(Interaccion.email == user.email, Interaccion.created_at >= inicio)
    )).scalar_one()
    if usadas >= settings.cuota_diaria:
        raise _error(status.HTTP_429_TOO_MANY_REQUESTS, "CUOTA_DIARIA_AGOTADA",
                     f"Se alcanzó el límite de {settings.cuota_diaria} preguntas por día.")


def costo_estimado(tokens: dict) -> float:
    return round(
        (tokens.get("input_tokens", 0) * settings.precio_entrada_mtok
         + tokens.get("output_tokens", 0) * settings.precio_salida_mtok
         + tokens.get("cache_read_input_tokens", 0) * settings.precio_cache_lectura_mtok
         + tokens.get("cache_creation_input_tokens", 0) * settings.precio_cache_escritura_mtok) / 1_000_000,
        6,
    )


async def preguntar(
    db: AsyncSession, db_llm: AsyncSession, user: AuthUser, conv: Conversacion, texto: str,
    progreso: llm.Progreso | None = None,
) -> dict:
    previos = await mensajes(db, conv.id)
    historial: list[dict] = []
    for m in previos:
        if m.rol == "assistant" and m.api_json:
            historial.extend(m.api_json)

    res = await llm.responder(texto, historial, db, db_llm, progreso=progreso)
    fuentes = await indicadores.frescura(db)

    ahora = _ahora()
    m_user = Mensaje(conversacion_id=conv.id, rol="user", texto=texto, created_at=ahora)
    respuesta = {
        "interpretacion": res.interpretacion, "bloques": res.bloques, "fuentes": fuentes,
        "sql": res.sql, "sugerencias": res.sugerencias, "error": bool(res.error),
    }
    m_asist = Mensaje(conversacion_id=conv.id, rol="assistant", texto=res.texto, respuesta=respuesta,
                      api_json=res.mensajes_api, created_at=ahora)
    db.add_all([m_user, m_asist])
    if not previos and conv.titulo == "Nueva consulta":
        conv.titulo = texto[:80]
    conv.updated_at = ahora
    await db.flush()
    db.add(Interaccion(
        mensaje_id=m_asist.id, conversacion_id=conv.id, email=user.email, pregunta=texto,
        tools=res.traza, sql=res.sql, filas_devueltas=res.filas_devueltas, latencia_ms=res.latencia_ms,
        tokens=res.tokens, costo_estimado_usd=costo_estimado(res.tokens), modelo=settings.modelo,
        error=res.error, created_at=ahora,
    ))
    await db.flush()
    return {"mensaje_id": m_asist.id, "texto": res.texto, **{k: respuesta[k] for k in
            ("interpretacion", "bloques", "fuentes", "sql", "sugerencias")}}


async def dar_feedback(db: AsyncSession, user: AuthUser, mensaje_id: str, valor: int, comentario: str | None) -> None:
    m = await db.get(Mensaje, mensaje_id)
    if m is None or m.rol != "assistant":
        raise _error(404, "MENSAJE_NO_ENCONTRADO", "Mensaje no encontrado")
    await obtener(db, user, m.conversacion_id)  # 404 si la conversación no es del usuario
    f = (await db.execute(
        select(Feedback).where(Feedback.mensaje_id == mensaje_id, Feedback.email == user.email)
    )).scalar_one_or_none()
    if f is None:
        db.add(Feedback(mensaje_id=mensaje_id, email=user.email, valor=valor, comentario=comentario, created_at=_ahora()))
    else:
        f.valor, f.comentario = valor, comentario
    await db.flush()
