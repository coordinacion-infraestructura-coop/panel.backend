import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AtpInternoPago(Base):
    """Pago de ATP Interno de Gobierno, una fila por fila de la pestaña "ATP ACUMULADO" de la
    planilla "4. ATP 2026" (spec-atp-interno.md §2). Distinta de `atp_compromisos` y nunca se
    suma con ella (ADR-029). Se reemplaza entera en cada corrida, por `anio_planilla`."""

    __tablename__ = "atp_interno_pagos"
    __table_args__ = (Index("ix_atp_interno_anio_codigo", "anio", "codigo_indec"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    anio_planilla: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fila: Mapped[int] = mapped_column(Integer, nullable=False)
    codigo_indec: Mapped[str] = mapped_column(String(6), nullable=False)
    localidad: Mapped[str | None] = mapped_column(String(150))
    departamento: Mapped[str | None] = mapped_column(String(100))
    fecha: Mapped[date | None] = mapped_column(Date)  # NULL si el serial de la planilla es imposible
    anio: Mapped[int] = mapped_column(Integer, nullable=False)  # año de `fecha`, o `anio_planilla`
    monto: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    # Sensible (spec §5): se guarda para un uso futuro, ningún endpoint lo devuelve.
    referente: Mapped[str | None] = mapped_column(String(120))
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AtpInternoSyncLog(Base):
    """Una fila por corrida (append-only, como `atp_sync_log`)."""

    __tablename__ = "atp_interno_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estado: Mapped[str] = mapped_column(String(20), nullable=False)  # ok | error | frenado
    anio_planilla: Mapped[int | None] = mapped_column(Integer)
    filas_leidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_cargadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_descartadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalias: Mapped[str | None] = mapped_column(Text)  # JSON: lista de {tipo, fila, detalle}
    mensaje: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str | None] = mapped_column(String(50))
