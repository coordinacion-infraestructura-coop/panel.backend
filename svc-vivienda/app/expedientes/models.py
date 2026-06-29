import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EstadoExpediente(str, Enum):
    INGRESADO = "INGRESADO"
    EN_EVALUACION = "EN_EVALUACION"
    DOCUMENTACION_PENDIENTE = "DOCUMENTACION_PENDIENTE"
    APROBADO = "APROBADO"
    EN_LISTA_ESPERA = "EN_LISTA_ESPERA"
    ASIGNADO = "ASIGNADO"
    RECHAZADO = "RECHAZADO"
    BAJA = "BAJA"


# Transiciones válidas definidas como constante (ADR: lógica de negocio en service.py)
TRANSICIONES_VALIDAS: dict[EstadoExpediente, list[EstadoExpediente]] = {
    EstadoExpediente.INGRESADO: [EstadoExpediente.EN_EVALUACION],
    EstadoExpediente.EN_EVALUACION: [
        EstadoExpediente.DOCUMENTACION_PENDIENTE,
        EstadoExpediente.APROBADO,
        EstadoExpediente.RECHAZADO,
    ],
    EstadoExpediente.DOCUMENTACION_PENDIENTE: [EstadoExpediente.EN_EVALUACION],
    EstadoExpediente.APROBADO: [EstadoExpediente.EN_LISTA_ESPERA],
    EstadoExpediente.EN_LISTA_ESPERA: [EstadoExpediente.ASIGNADO],
    EstadoExpediente.ASIGNADO: [EstadoExpediente.BAJA],
    EstadoExpediente.RECHAZADO: [EstadoExpediente.INGRESADO],
    EstadoExpediente.BAJA: [],
}


class Expediente(Base):
    __tablename__ = "viv_expedientes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    numero_expediente: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    beneficiario_id: Mapped[str] = mapped_column(String(36), ForeignKey("viv_beneficiarios.id"), nullable=False)
    programa_id: Mapped[str] = mapped_column(String(36), ForeignKey("viv_programas.id"), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(30), nullable=False, default=EstadoExpediente.INGRESADO.value
    )
    fecha_solicitud: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    fecha_resolucion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observaciones: Mapped[str | None] = mapped_column(Text)
    prioridad: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[str | None] = mapped_column(String(200))

    historial: Mapped[list["HistorialExpediente"]] = relationship(
        back_populates="expediente", cascade="all, delete-orphan"
    )


class HistorialExpediente(Base):
    __tablename__ = "viv_historial_expedientes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    expediente_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_expedientes.id", ondelete="CASCADE"), nullable=False
    )
    estado_anterior: Mapped[str | None] = mapped_column(String(30))
    estado_nuevo: Mapped[str] = mapped_column(String(30), nullable=False)
    observacion: Mapped[str | None] = mapped_column(Text)
    actor_uid: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_rol: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    expediente: Mapped["Expediente"] = relationship(back_populates="historial")
