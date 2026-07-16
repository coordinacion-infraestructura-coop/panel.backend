import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChecklistTecnicoCC(Base):
    """Snapshot sincronizado desde la pestaña "Base TOTAL" del Google Sheet del área técnica."""

    __tablename__ = "viv_cc_checklist_tecnico"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    localidad: Mapped[str] = mapped_column(String(150), nullable=False)
    departamento: Mapped[str | None] = mapped_column(String(100))
    expediente: Mapped[str | None] = mapped_column(String(60))
    orden_sheet: Mapped[int | None] = mapped_column(Integer)
    tipo: Mapped[str | None] = mapped_column(String(1))
    intendente: Mapped[str | None] = mapped_column(String(200))
    telefono: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(200))
    contacto_tecnico: Mapped[str | None] = mapped_column(String(300))
    monto_convenio: Mapped[float | None] = mapped_column(Numeric(18, 2))
    cordon_cuneta_ml: Mapped[float | None] = mapped_column(Numeric(10, 2))
    adoquinado_m2: Mapped[float | None] = mapped_column(Numeric(10, 2))
    estado_expediente: Mapped[str | None] = mapped_column(String(200))
    observaciones: Mapped[str | None] = mapped_column(Text)
    fecha_radicacion: Mapped[date | None] = mapped_column(Date)
    reparticion: Mapped[str | None] = mapped_column(String(200))
    municipio_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("viv_cordon_cuneta.id"))
    sheet_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
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

    items: Mapped[list["ChecklistItemCC"]] = relationship(
        order_by="ChecklistItemCC.item_num", viewonly=True
    )


class ChecklistItemCC(Base):
    """Un ítem (de los 19 fijos) del checklist técnico para una localidad."""

    __tablename__ = "viv_cc_checklist_items"
    __table_args__ = (UniqueConstraint("checklist_id", "item_num", name="uq_cc_checklist_item"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checklist_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_cc_checklist_tecnico.id", ondelete="CASCADE"), nullable=False
    )
    item_num: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    item_label: Mapped[str] = mapped_column(String(150), nullable=False)
    valor: Mapped[str] = mapped_column(String(200), nullable=False)


class SyncLogCC(Base):
    """Una fila por corrida de sincronización del checklist técnico."""

    __tablename__ = "viv_cc_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filas_leidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_insertadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_actualizadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errores: Mapped[str | None] = mapped_column(Text)  # JSON serializado (lista de {fila, motivo})
    triggered_by: Mapped[str | None] = mapped_column(String(50))
