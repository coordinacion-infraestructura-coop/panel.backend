import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TipoBien(str, Enum):
    VIVIENDA = "VIVIENDA"
    LOTE = "LOTE"


class Asignacion(Base):
    __tablename__ = "viv_asignaciones"
    __table_args__ = (UniqueConstraint("expediente_id", name="uq_asignacion_expediente"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    expediente_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_expedientes.id"), nullable=False, unique=True
    )
    tipo_bien: Mapped[str] = mapped_column(String(20), nullable=False)
    identificador_bien: Mapped[str] = mapped_column(String(100), nullable=False)
    domicilio_bien: Mapped[str | None] = mapped_column(String(300))
    fecha_escritura: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observaciones: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
