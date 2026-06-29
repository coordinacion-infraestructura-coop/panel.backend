import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Beneficiario(Base):
    __tablename__ = "viv_beneficiarios"
    __table_args__ = (UniqueConstraint("dni", name="uq_beneficiario_dni"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dni: Mapped[str] = mapped_column(String(20), nullable=False)
    cuil: Mapped[str | None] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha_nacimiento: Mapped[str | None] = mapped_column(String(10))
    email: Mapped[str | None] = mapped_column(String(200))
    telefono: Mapped[str | None] = mapped_column(String(30))
    domicilio_calle: Mapped[str | None] = mapped_column(String(200))
    domicilio_numero: Mapped[str | None] = mapped_column(String(20))
    domicilio_localidad: Mapped[str | None] = mapped_column(String(100))
    domicilio_departamento: Mapped[str | None] = mapped_column(String(100))
    grupo_familiar_count: Mapped[int | None] = mapped_column(Integer)
    ingreso_mensual: Mapped[float | None] = mapped_column(Numeric(14, 2))
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[str | None] = mapped_column(String(200))
