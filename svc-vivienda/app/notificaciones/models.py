"""Notificaciones internas del sistema — feed global con estado de lectura por usuario.

Módulo transversal (montado en `/api/v1/notificaciones`, sin prefijo `/vivienda` — mismo
criterio que `app/portal/`, ADR-007 / ADR-019). Una fila por evento del sistema en
`portal_notificaciones`; el estado leído/no leído es por usuario en
`portal_notificacion_lecturas` (no se duplica la notificación por destinatario).

Spec: docs/files/spec-notificaciones.md
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

NIVELES = ("info", "exito", "advertencia", "error")
DESTINO_TIPOS = ("global", "rol", "secretaria")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Notificacion(Base):
    """Una alerta interna del feed. `destino_tipo` = a quién le llega:
    `global` (todos), `rol` (`destino_valor` = nombre de rol) o `secretaria`
    (`destino_valor` = id de secretaría)."""

    __tablename__ = "portal_notificaciones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    nivel: Mapped[str] = mapped_column(String(20), nullable=False, server_default="info")
    origen: Mapped[str] = mapped_column(String(60), nullable=False, server_default="sistema")
    enlace: Mapped[str | None] = mapped_column(String(500))
    destino_tipo: Mapped[str] = mapped_column(String(20), nullable=False, server_default="global")
    destino_valor: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "nivel IN ('info','exito','advertencia','error')", name="ck_notif_nivel"
        ),
        CheckConstraint(
            "destino_tipo IN ('global','rol','secretaria')", name="ck_notif_destino_tipo"
        ),
        Index("ix_portal_notificaciones_created_at", "created_at"),
    )


class NotificacionLectura(Base):
    """Marca de "leída" de una notificación por un usuario concreto. La ausencia de
    fila = no leída."""

    __tablename__ = "portal_notificacion_lecturas"

    notificacion_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("portal_notificaciones.id", ondelete="CASCADE"),
        primary_key=True,
    )
    usuario_email: Mapped[str] = mapped_column(String(200), primary_key=True)
    leida_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    __table_args__ = (Index("ix_portal_notif_lecturas_usuario", "usuario_email"),)
