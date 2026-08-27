import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CatalogoEstadoExpediente(Base):
    """Catálogo administrable, compartido entre CC/CH/ML — hoy vive en la solapa "Validaciones" del Excel."""

    __tablename__ = "viv_checklist_estado_expediente"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CatalogoReparticion(Base):
    """Catálogo administrable — `programa` NULL significa que aplica a los 3 programas."""

    __tablename__ = "viv_checklist_reparticion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    programa: Mapped[str | None] = mapped_column(String(2))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ChecklistTecnico(Base):
    """Fila 1:1 con una entidad existente (viv_cordon_cuneta / viv_cordoba_hogar / viv_ml_proyectos).

    `entidad_id` no lleva FK real de Postgres porque apunta a una de 3 tablas distintas según
    `programa` (mismo patrón polimórfico que ya usa `viv_ml_proyectos.tipo`) — `service.py` valida
    que la entidad exista antes de escribir.
    """

    __tablename__ = "viv_checklist_tecnico"
    __table_args__ = (UniqueConstraint("programa", "entidad_id", name="uq_checklist_programa_entidad"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    programa: Mapped[str] = mapped_column(String(2), nullable=False)  # 'cc' | 'ch' | 'ml'
    entidad_id: Mapped[str] = mapped_column(String(36), nullable=False)
    estado_expediente_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("viv_checklist_estado_expediente.id")
    )
    fecha_radicacion: Mapped[date | None] = mapped_column(Date)
    reparticion_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_checklist_reparticion.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by: Mapped[str | None] = mapped_column(String(200))


class ChecklistItem(Base):
    """Un ítem (o sub-ítem) del checklist de documentación. `valor` es uno de los 5 estados de §3 del spec."""

    __tablename__ = "viv_checklist_items"
    __table_args__ = (
        UniqueConstraint("checklist_id", "item_num", "sub_item_num", name="uq_checklist_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checklist_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"), nullable=False
    )
    item_num: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sub_item_num: Mapped[int | None] = mapped_column(SmallInteger)
    valor: Mapped[str] = mapped_column(String(30), nullable=False)


class ChecklistObraHito(Base):
    """Hito de ejecución de obra — solo `programa='cc'` en esta entrega.

    No persiste `monto`: se recalcula en `service.py` sobre `viv_cordon_cuneta.monto` vigente en
    cada lectura (decisión confirmada — un hito ya acreditado debe reflejar el monto actual del
    convenio, no un valor congelado al momento de acreditarlo).
    """

    __tablename__ = "viv_checklist_obra_hitos"
    __table_args__ = (UniqueConstraint("checklist_id", "tipo", name="uq_checklist_hito"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checklist_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # 'anticipo' | '40' | '70' | '100'
    fecha_acreditado: Mapped[date | None] = mapped_column(Date)
