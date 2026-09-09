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
    Text,
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
    # `en_ruta=False` → estado de excepción (RECHAZADO por M/C, SIN AUTORIZACION MIN.GOB): no es
    # parte del camino lineal del stepper; se marca solo si el expediente lo transitó de verdad.
    en_ruta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CatalogoReparticion(Base):
    """Catálogo administrable — `programa` NULL significa que aplica a los 3 programas."""

    __tablename__ = "viv_checklist_reparticion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    programa: Mapped[str | None] = mapped_column(String(2))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CatalogoItemEstado(Base):
    """Catálogo administrable de "Estado de la documentación" (por ítem del checklist).

    Antes era un enum fijo en código (`ValorItem`); el área técnica pidió poder editarlo
    (corrección DGV 2026-09, spec-checklist-tecnico-dgv.md v1.2.0). Misma forma que
    `viv_cc_estados` — `bg`/`text_color` para el chip de color en el frontend.
    """

    __tablename__ = "viv_checklist_item_estado"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bg: Mapped[str] = mapped_column(String(10), nullable=False, default="#f1f5f9")
    text_color: Mapped[str] = mapped_column(String(10), nullable=False, default="#64748b")
    # Marca el estado "terminado" del ítem — lo usan resumen_territorial / tablero para
    # contar documentación faltante. Editable por Admin (antes era el literal "completo").
    es_completo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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
    """Un ítem (o sub-ítem) del checklist de documentación.

    `item_estado_id` apunta al catálogo administrable `viv_checklist_item_estado` (antes era
    un enum fijo `valor`, spec v1.2.0).
    """

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
    item_estado_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("viv_checklist_item_estado.id"), nullable=False
    )


class ChecklistObraHito(Base):
    """Hito de ejecución de obra — los 3 programas (CC/CH/ML) desde la corrección DGV 2026-09.

    No persiste `monto`: se recalcula en `service.py` sobre el `monto` vigente de la entidad
    del programa (`viv_cordon_cuneta` / `viv_cordoba_hogar` / `viv_ml_proyectos`) en cada
    lectura — un hito ya acreditado debe reflejar el monto actual del convenio, no un valor
    congelado. Proporciones 50/25/25/0 (confirmadas sobre el Excel para CC y CH; para ML se
    asume la misma a falta de datos de referencia).
    """

    __tablename__ = "viv_checklist_obra_hitos"
    __table_args__ = (UniqueConstraint("checklist_id", "tipo", name="uq_checklist_hito"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checklist_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # 'anticipo' | '40' | '70' | '100'
    fecha_acreditado: Mapped[date | None] = mapped_column(Date)


class ChecklistObraObs(Base):
    """Bitácora de observaciones de la etapa de obra — misma forma que `viv_*_pedidos`
    (observaciones del expediente): una entrada fechada por carga, con el usuario que la hizo.
    Reemplaza al campo único `viv_checklist_tecnico.obs_obra` (spec v1.3.0).
    """

    __tablename__ = "viv_checklist_obra_obs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checklist_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"), nullable=False
    )
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
    created_by_nombre: Mapped[str | None] = mapped_column(String(255))


class ChecklistEstadoHist(Base):
    """Cada vez que cambia el "Estado del expediente" se registra acá — sirve para saber si el
    expediente transitó un estado de excepción (RECHAZADO / SIN AUTORIZACION), que no está en el
    camino lineal del stepper (spec v1.4.0). Solo se escribe en cambios de estado, no en cada PATCH.
    """

    __tablename__ = "viv_checklist_estado_hist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checklist_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_checklist_tecnico.id", ondelete="CASCADE"), nullable=False
    )
    estado_expediente_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("viv_checklist_estado_expediente.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
