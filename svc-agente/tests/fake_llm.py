"""Cliente LLM falso: devuelve respuestas guionadas con la misma forma que el SDK."""
from types import SimpleNamespace


def _bloque(d: dict):
    obj = SimpleNamespace(**d)
    obj.model_dump = lambda exclude_none=True, _d=d: dict(_d)
    return obj


def tool(id_: str, nombre: str, entrada: dict) -> dict:
    return {"type": "tool_use", "id": id_, "name": nombre, "input": entrada}


def texto(t: str) -> dict:
    return {"type": "text", "text": t}


class FakeLLM:
    def __init__(self, guion: list[tuple[str, list[dict]]]):
        self.guion = list(guion)
        self.llamadas: list[dict] = []

    async def crear(self, *, system, tools, messages):
        self.llamadas.append({"system": system, "tools": tools, "messages": [dict(m) for m in messages]})
        if not self.guion:
            raise AssertionError("El modelo falso se quedó sin respuestas")
        stop, contenido = self.guion.pop(0)
        return SimpleNamespace(
            stop_reason=stop, content=[_bloque(c) for c in contenido],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=50,
                                  cache_creation_input_tokens=0),
        )
