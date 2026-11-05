"""Tablas propias del servicio (spec §6.4). Schema por defecto (public), NO `ag`: el rol
`agente_llm` no puede leerlas."""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Conversacion(Base):
    __tablename__ = "ag_conversaciones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(200), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Mensaje(Base):
    __tablename__ = "ag_mensajes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversacion_id: Mapped[str] = mapped_column(String(36), ForeignKey("ag_conversaciones.id"), index=True)
    rol: Mapped[str] = mapped_column(String(10))  # user | assistant
    texto: Mapped[str] = mapped_column(Text)
    # Sólo en assistant: interpretacion, bloques, sugerencias, fuentes, sql
    respuesta: Mapped[dict | None] = mapped_column(JSON)
    # Sólo en assistant: mensajes de la API agregados en el turno (historial append-only)
    api_json: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Interaccion(Base):
    """Audit log del servicio: una fila por pregunta."""

    __tablename__ = "ag_interacciones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mensaje_id: Mapped[str | None] = mapped_column(String(36), index=True)
    conversacion_id: Mapped[str | None] = mapped_column(String(36))
    email: Mapped[str] = mapped_column(String(200), index=True)
    pregunta: Mapped[str] = mapped_column(Text)
    tools: Mapped[list | None] = mapped_column(JSON)
    sql: Mapped[list | None] = mapped_column(JSON)
    filas_devueltas: Mapped[int] = mapped_column(Integer, default=0)
    latencia_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[dict | None] = mapped_column(JSON)
    costo_estimado_usd: Mapped[float | None] = mapped_column(Float)
    modelo: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Feedback(Base):
    __tablename__ = "ag_feedback"
    __table_args__ = (UniqueConstraint("mensaje_id", "email", name="uq_ag_feedback_mensaje_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mensaje_id: Mapped[str] = mapped_column(String(36), ForeignKey("ag_mensajes.id"))
    email: Mapped[str] = mapped_column(String(200))
    valor: Mapped[int] = mapped_column(SmallInteger)  # 1 | -1
    comentario: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
