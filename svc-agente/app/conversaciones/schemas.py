from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversacionCrear(BaseModel):
    titulo: str | None = Field(default=None, max_length=200)


class ConversacionOut(BaseModel):
    id: str
    titulo: str
    created_at: datetime
    updated_at: datetime


class ConversacionLista(BaseModel):
    items: list[ConversacionOut]
    total: int
    limit: int
    offset: int


class MensajeOut(BaseModel):
    id: str
    rol: str
    texto: str
    respuesta: dict[str, Any] | None = None
    created_at: datetime


class ConversacionDetalle(ConversacionOut):
    mensajes: list[MensajeOut]


class PreguntaIn(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class RespuestaOut(BaseModel):
    mensaje_id: str
    texto: str
    interpretacion: str | None
    bloques: list[dict[str, Any]]
    fuentes: list[dict[str, Any]]
    sql: list[str]
    sugerencias: list[str]


class FeedbackIn(BaseModel):
    valor: Literal[1, -1]
    comentario: str | None = Field(default=None, max_length=2000)
