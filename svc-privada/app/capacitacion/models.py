"""Inscripciones a una capacitación, espejo de las respuestas de un formulario de Google
(docs/files/spec-privada-sync-capacitacion.md §6). El correo no se guarda: solo su hash, para
deduplicar."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CapacitacionInscripcion(Base):
    __tablename__ = "priv_capacitacion_inscripcion"
    __table_args__ = (
        UniqueConstraint("capacitacion", "marca_temporal", "email_hash", name="uq_priv_capacitacion_inscripcion"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capacitacion: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    fila_origen: Mapped[int] = mapped_column(Integer, nullable=False)
    marca_temporal: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    apellido: Mapped[str | None] = mapped_column(String(120))
    nombre: Mapped[str | None] = mapped_column(String(120))
    cargo: Mapped[str | None] = mapped_column(String(60))
    localidad_texto: Mapped[str | None] = mapped_column(String(200))
    departamento_texto: Mapped[str | None] = mapped_column(String(120))
    id_geo: Mapped[str | None] = mapped_column(String(30))
    match_tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
