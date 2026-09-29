import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExtTransferencia(Base):
    """Fila larga de transferencias automáticas a municipios/comunas
    (spec-resumen-territorial-tablero-v2.md §2.2). `UNIQUE` en
    (periodo, tipo, nombre_pdf, concepto) permite re-correr el mismo mes
    (el sitio a veces publica versiones -v1/-v2 del mismo período)."""

    __tablename__ = "ext_transferencias"
    __table_args__ = (
        UniqueConstraint("periodo", "tipo", "nombre_pdf", "concepto", name="uq_ext_transferencias_natural"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    periodo: Mapped[date] = mapped_column(Date, nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # "municipio" | "comuna"
    id_geo: Mapped[str | None] = mapped_column(String(20))
    codigo_indec: Mapped[str | None] = mapped_column(String(20))
    nombre_pdf: Mapped[str] = mapped_column(String(200), nullable=False)
    departamento_pdf: Mapped[str] = mapped_column(String(100), nullable=False)
    concepto: Mapped[str] = mapped_column(String(50), nullable=False)
    monto: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    match_tipo: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ExtTransferenciaSyncLog(Base):
    """Una fila por corrida del ETL mensual (o carga manual de respaldo).
    Append-only, mismo criterio que `viv_cc_sync_log`/`viv_informe_snapshot`:
    no se borra, se audita agregando filas."""

    __tablename__ = "ext_transferencias_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    periodo: Mapped[date] = mapped_column(Date, nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    filas_procesadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_sin_match: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalias: Mapped[dict | list | None] = mapped_column(JSON)
    corrida_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    disparado_por: Mapped[str | None] = mapped_column(String(80))
