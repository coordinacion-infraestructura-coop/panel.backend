from datetime import datetime

from pydantic import BaseModel, Field


class NotificacionOut(BaseModel):
    id: str
    titulo: str
    mensaje: str
    nivel: str
    origen: str
    enlace: str | None = None
    destino_tipo: str
    destino_valor: str | None = None
    created_at: datetime
    leida: bool


class NotificacionesListResponse(BaseModel):
    items: list[NotificacionOut]
    total: int
    no_leidas: int


class NotificacionIn(BaseModel):
    """Alta de una notificación. La usa `POST /internal/notificaciones` (IAM-only);
    no hay alta desde la UI todavía."""

    titulo: str = Field(min_length=1, max_length=200)
    mensaje: str = Field(min_length=1)
    nivel: str = Field(default="info", pattern="^(info|exito|advertencia|error)$")
    origen: str = Field(default="sistema", max_length=60)
    enlace: str | None = Field(default=None, max_length=500)
    destino_tipo: str = Field(default="global", pattern="^(global|rol|secretaria)$")
    destino_valor: str | None = Field(default=None, max_length=60)
