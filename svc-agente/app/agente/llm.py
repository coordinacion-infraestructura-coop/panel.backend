"""Loop de tool use contra Claude en Vertex AI (spec §6.1). Loop propio, sin framework.

El historial de la conversación se reenvía tal cual se recibió (append-only, incluidos los bloques
de thinking y tool_use/tool_result): así no se rompe el chequeo de historial de los modelos con
pensamiento preservado, y el prompt caching reutiliza el prefijo.
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.agente.herramientas import TOOLS, Turno, a_json, ejecutar
from app.agente.prompt import system_prompt
from app.config import settings

log = logging.getLogger(__name__)

Progreso = Callable[[str], Awaitable[None]]


class ClienteLLM(Protocol):
    async def crear(self, *, system: list[dict], tools: list[dict], messages: list[dict]) -> Any: ...


class ClienteVertex:
    def __init__(self) -> None:
        from anthropic import AsyncAnthropicVertex

        self._c = AsyncAnthropicVertex(project_id=settings.vertex_project_id, region=settings.vertex_region)

    async def crear(self, *, system, tools, messages):
        return await self._c.messages.create(
            model=settings.modelo, max_tokens=settings.max_tokens, system=system, tools=tools,
            messages=messages, output_config={"effort": settings.esfuerzo},
        )


_cliente: ClienteLLM | None = None


def cliente() -> ClienteLLM:
    global _cliente
    if _cliente is None:
        _cliente = ClienteVertex()
    return _cliente


def set_cliente(c: ClienteLLM | None) -> None:
    """Para tests."""
    global _cliente
    _cliente = c


@dataclass
class Resultado:
    texto: str
    interpretacion: str | None
    sugerencias: list[str]
    bloques: list[dict]
    sql: list[str]
    traza: list[dict]
    mensajes_api: list[dict]  # lo que se agregó al historial en este turno
    tokens: dict = field(default_factory=dict)
    latencia_ms: int = 0
    error: str | None = None
    filas_devueltas: int = 0


def _bloque_a_dict(b: Any) -> dict:
    return b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b)


def _sumar_uso(acum: dict, uso: Any) -> None:
    if uso is None:
        return
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        acum[k] = acum.get(k, 0) + (getattr(uso, k, 0) or 0)


async def responder(
    pregunta: str, historial: list[dict], db: AsyncSession, db_llm: AsyncSession,
    progreso: Progreso | None = None, hoy: date | None = None,
) -> Resultado:
    t0 = time.monotonic()
    turno = Turno()
    hoy = hoy or date.today()
    nuevos: list[dict] = [{
        "role": "user",
        "content": [{"type": "text", "text": f"(Fecha de hoy: {hoy.isoformat()})\n\n{pregunta}"}],
    }]
    system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    tokens: dict = {}
    final: dict | None = None
    texto_libre = ""
    error = None

    try:
        for ronda in range(settings.max_rondas_tools + 1):
            mensajes = historial + nuevos
            if ronda == settings.max_rondas_tools:
                mensajes = mensajes + [{"role": "user", "content": [{"type": "text", "text":
                    "Se alcanzó el máximo de consultas para esta pregunta. Respondé ahora con lo que tenés, llamando a `responder`."}]}]
            resp = await cliente().crear(system=system, tools=TOOLS, messages=mensajes)
            _sumar_uso(tokens, getattr(resp, "usage", None))
            contenido = [_bloque_a_dict(b) for b in resp.content]
            nuevos.append({"role": "assistant", "content": contenido})

            if resp.stop_reason == "refusal":
                texto_libre = "No puedo responder esa consulta. Probá reformularla en términos de los programas y gestiones de la Secretaría."
                break

            usos = [b for b in contenido if b.get("type") == "tool_use"]
            texto_libre = "\n".join(b["text"] for b in contenido if b.get("type") == "text").strip() or texto_libre
            if not usos:
                break

            resultados = []
            for u in usos:
                if u["name"] == "responder":
                    final = u["input"]
                    resultados.append({"type": "tool_result", "tool_use_id": u["id"], "content": "Respuesta enviada al usuario."})
                    continue
                if final is not None:
                    resultados.append({"type": "tool_result", "tool_use_id": u["id"], "is_error": True,
                                       "content": "No se ejecutó: la respuesta ya fue enviada."})
                    continue
                if progreso:
                    await progreso(u["name"])
                t1 = time.monotonic()
                try:
                    res = await ejecutar(u["name"], u["input"], db, db_llm, turno)
                    es_error = "error" in res
                except Exception as e:  # la tool falló: el modelo lo ve y puede seguir
                    log.exception("Tool %s falló", u["name"])
                    res, es_error = {"error": f"Falla interna de la tool: {type(e).__name__}"}, True
                turno.traza.append({"tool": u["name"], "input": u["input"], "error": res.get("error"),
                                    "ms": int((time.monotonic() - t1) * 1000)})
                r = {"type": "tool_result", "tool_use_id": u["id"], "content": a_json(res)}
                if es_error:
                    r["is_error"] = True
                resultados.append(r)
            nuevos.append({"role": "user", "content": resultados})
            if final is not None:
                break
    except Exception as e:
        log.exception("Error llamando al modelo")
        error = f"{type(e).__name__}: {e}"[:500]

    if final is not None:
        ids = [i for i in final.get("bloques") or [] if i in turno.bloques]
        bloques = [turno.bloques[i] for i in ids]
        texto, interp, sug = final.get("texto") or "", final.get("interpretacion"), final.get("sugerencias") or []
    else:
        bloques = list(turno.bloques.values())
        texto = texto_libre or ("No pude completar la consulta en este momento. Probá de nuevo en unos minutos." if error else "")
        interp, sug = None, []

    # Si el turno terminó con un error o sin cerrar, el historial no debe quedar con un tool_use
    # sin su tool_result: se descarta lo nuevo salvo el mensaje del usuario y una respuesta en texto.
    if error or (nuevos[-1]["role"] == "assistant" and any(b.get("type") == "tool_use" for b in nuevos[-1]["content"])):
        nuevos = [nuevos[0], {"role": "assistant", "content": [{"type": "text", "text": texto or "(sin respuesta)"}]}]

    return Resultado(
        texto=texto, interpretacion=interp, sugerencias=sug[:3], bloques=bloques, sql=turno.sql,
        traza=turno.traza, mensajes_api=nuevos, tokens=tokens,
        latencia_ms=int((time.monotonic() - t0) * 1000), error=error, filas_devueltas=turno.filas_devueltas,
    )
