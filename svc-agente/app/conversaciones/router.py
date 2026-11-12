"""API del agente (spec §7). Prefijo /api/v1/agente."""
import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agente import indicadores
from app.agente.herramientas import a_json
from app.auth import ROLES_AGENTE, AuthUser, require_roles
from app.conversaciones import service
from app.conversaciones.schemas import (
    ConversacionCrear, ConversacionDetalle, ConversacionLista, ConversacionOut, FeedbackIn,
    MensajeOut, PreguntaIn, RespuestaOut,
)
from app.database import get_db, get_db_llm

router = APIRouter(tags=["agente"])
_auth = require_roles(*ROLES_AGENTE)

ETIQUETA_TOOL = {
    "resolver_territorio": "Buscando la localidad o el departamento",
    "estado_programa_territorio": "Consultando el estado de los programas",
    "ficha_territorio": "Armando la ficha del territorio",
    "montos": "Calculando montos",
    "pendientes": "Revisando demoras y pendientes",
    "consulta_sql": "Consultando los datos",
}


@router.get("/conversaciones", response_model=ConversacionLista)
async def listar(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 db: AsyncSession = Depends(get_db), user: AuthUser = Depends(_auth)):
    return await service.listar(db, user, limit, offset)


@router.post("/conversaciones", response_model=ConversacionOut, status_code=201)
async def crear(body: ConversacionCrear, db: AsyncSession = Depends(get_db), user: AuthUser = Depends(_auth)):
    return await service.crear(db, user, body.titulo)


@router.get("/conversaciones/{conv_id}", response_model=ConversacionDetalle)
async def detalle(conv_id: str, db: AsyncSession = Depends(get_db), user: AuthUser = Depends(_auth)):
    c = await service.obtener(db, user, conv_id)
    msgs = await service.mensajes(db, c.id)
    return ConversacionDetalle(
        id=c.id, titulo=c.titulo, created_at=c.created_at, updated_at=c.updated_at,
        mensajes=[MensajeOut(id=m.id, rol=m.rol, texto=m.texto, respuesta=m.respuesta, created_at=m.created_at) for m in msgs],
    )


@router.delete("/conversaciones/{conv_id}", status_code=204)
async def borrar(conv_id: str, db: AsyncSession = Depends(get_db), user: AuthUser = Depends(_auth)):
    await service.borrar(db, user, conv_id)


@router.post("/conversaciones/{conv_id}/mensajes", response_model=RespuestaOut)
async def preguntar(
    conv_id: str, body: PreguntaIn, stream: bool = Query(True),
    db: AsyncSession = Depends(get_db), db_llm: AsyncSession = Depends(get_db_llm),
    user: AuthUser = Depends(_auth),
):
    """Con `stream=true` (por defecto) responde Server-Sent Events: `progreso` mientras corren las
    tools y `respuesta` al final (o `error`). Con `stream=false`, JSON."""
    conv = await service.obtener(db, user, conv_id)
    await service.verificar_cuota(db, user)
    if not stream:
        return await service.preguntar(db, db_llm, user, conv, body.texto)

    # La sesión de la dependencia se cierra antes de que corra el cuerpo del stream (FastAPI ≥ 0.106):
    # el generador abre las suyas.
    from app.database import AsyncSessionLocal, LlmSessionLocal

    async def eventos():
        cola: asyncio.Queue = asyncio.Queue()

        async def progreso(tool: str) -> None:
            await cola.put(("progreso", {"tool": tool, "texto": ETIQUETA_TOOL.get(tool, "Consultando")}))

        async def trabajo():
            try:
                async with AsyncSessionLocal() as s, LlmSessionLocal() as s_llm:
                    c = await service.obtener(s, user, conv_id)
                    r = await service.preguntar(s, s_llm, user, c, body.texto, progreso=progreso)
                    await s.commit()
                await cola.put(("respuesta", r))
            except Exception:
                await cola.put(("error", {"code": "ERROR_INTERNO", "message": "No se pudo completar la consulta."}))
            await cola.put(None)

        tarea = asyncio.create_task(trabajo())
        yield _sse("progreso", {"texto": "Pensando la consulta"})
        while True:
            item = await cola.get()
            if item is None:
                break
            yield _sse(*item)
        await tarea

    return StreamingResponse(eventos(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(evento: str, datos: dict) -> str:
    return f"event: {evento}\ndata: {a_json(datos, ascii=True)}\n\n"


@router.post("/mensajes/{mensaje_id}/feedback", status_code=204)
async def feedback(mensaje_id: str, body: FeedbackIn, db: AsyncSession = Depends(get_db), user: AuthUser = Depends(_auth)):
    await service.dar_feedback(db, user, mensaje_id, body.valor, body.comentario)


@router.get("/estado")
async def estado(db: AsyncSession = Depends(get_db), user: AuthUser = Depends(_auth)):
    return {"fuentes": await indicadores.frescura(db)}
