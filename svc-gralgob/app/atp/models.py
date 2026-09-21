import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AtpCompromiso(Base):
    """Compromiso ATP (Aporte del Tesoro Provincial) sincronizado desde la hoja
    "BD" del Sheet "ATP - Compromiso Gobernador". Ver
    docs/files/spec-sync-atp-compromiso-gobernador.md.
    """

    __tablename__ = "atp_compromisos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Única clave natural razonable en esta hoja: el índice manual de la
    # columna "#" no es estable, y no hay expediente/destino que garantice
    # unicidad (una misma localidad puede tener varios compromisos con
    # destinos parecidos). Mismo criterio que gas_pit_acciones_territorio.
    sheet_row_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    departamento: Mapped[str | None] = mapped_column(String(100))
    localidad: Mapped[str | None] = mapped_column(String(150))
    # A qué ministerio/secretaría se derivó la ejecución del compromiso.
    # "Gobierno" = queda dentro de la propia Secretaría General de Gobierno.
    ministerio_destino: Mapped[str | None] = mapped_column(String(100))
    fecha_anuncio: Mapped[date | None] = mapped_column(Date)
    nro_expediente: Mapped[str | None] = mapped_column(String(60))
    derivado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    monto: Mapped[float | None] = mapped_column(Numeric(18, 2))
    destino: Mapped[str | None] = mapped_column(Text)
    # Mirror del valor ya calculado por la fórmula FILTER del Sheet — NO se
    # recalcula acá. La hoja fuerza este valor a 0 cuando ministerio_destino
    # != "Gobierno" (el saldo de lo derivado no se trackea en esta hoja). Ver
    # spec §3.2.
    saldo_atp: Mapped[float | None] = mapped_column(Numeric(18, 2))
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    cronograma: Mapped[list["AtpCronogramaPago"]] = relationship(viewonly=True)


class AtpCronogramaPago(Base):
    """Cronograma de pago mensual, denormalizado desde las columnas
    mensuales de la hoja "BD" (formato de encabezado "<Mes> <AA>", ej.
    "Marzo 25" — hoy llega a "Diciembre 27" y el área lo sigue extendiendo).
    El signo se mirror-ea tal cual viene del Sheet (negativo = pagado)."""

    __tablename__ = "atp_cronograma_pagos"
    __table_args__ = (
        UniqueConstraint("compromiso_id", "periodo", name="uq_atp_cronograma_compromiso_periodo"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    compromiso_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("atp_compromisos.id", ondelete="CASCADE"), nullable=False
    )
    periodo: Mapped[date] = mapped_column(Date, nullable=False)  # primer día del mes
    monto: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)


class AtpSyncLog(Base):
    """Una fila por corrida de sincronización de la hoja "BD"."""

    __tablename__ = "atp_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filas_leidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_insertadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_actualizadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errores: Mapped[str | None] = mapped_column(Text)  # JSON serializado (lista de {fila, motivo})
    triggered_by: Mapped[str | None] = mapped_column(String(50))
