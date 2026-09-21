import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
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


class GasPitObra(Base):
    """Obra de gas sincronizada desde 'MATRIZ (NO TOMAR)', filtrada a
    SUB-TIPO DE OBRA = "E- OBRAS DE GAS". Ver docs/files/spec-sync-gasifera-pit.md.
    """

    __tablename__ = "gas_pit_obras"
    __table_args__ = (
        UniqueConstraint("nombre_obra_norm", "departamento_norm", name="uq_gas_pit_obra_nombre_depto"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    spip: Mapped[str | None] = mapped_column(String(30))  # crudo; "-" -> NULL; NO es único ni PK
    expediente: Mapped[str | None] = mapped_column(String(60))
    division: Mapped[str | None] = mapped_column(String(50))
    nombre_obra: Mapped[str] = mapped_column(String(300), nullable=False)
    # Columna normalizada (lower/trim) usada solo para la clave natural del upsert —
    # mismo patrón que el índice único de viv_cc_checklist_tecnico, pero como columna
    # generada en Python (no en SQL) porque nombre_obra no es tan corto/estable como
    # localidad+departamento en CC.
    nombre_obra_norm: Mapped[str] = mapped_column(String(300), nullable=False)
    departamento_norm: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    tipo_obra: Mapped[str | None] = mapped_column(String(100))
    sub_tipo_obra: Mapped[str] = mapped_column(String(50), nullable=False, default="E- OBRAS DE GAS")
    contratista: Mapped[str | None] = mapped_column(String(200))
    estado_obra: Mapped[str | None] = mapped_column(String(60))
    estado_resumen: Mapped[str | None] = mapped_column(String(30))
    departamento: Mapped[str | None] = mapped_column(String(100))
    avance: Mapped[float | None] = mapped_column(Numeric(5, 4))
    repla_inicial: Mapped[date | None] = mapped_column(Date)
    fecha_lic: Mapped[date | None] = mapped_column(Date)
    vencimiento: Mapped[date | None] = mapped_column(Date)
    plazo_vigente_dias: Mapped[int | None] = mapped_column(Integer)
    plazo_original: Mapped[int | None] = mapped_column(Integer)
    contrato_base: Mapped[float | None] = mapped_column(Numeric(18, 2))
    ampliacion: Mapped[float | None] = mapped_column(Numeric(18, 2))
    enmienda: Mapped[float | None] = mapped_column(Numeric(18, 2))
    importe_obra_actualizado: Mapped[float | None] = mapped_column(Numeric(18, 2))
    importe_dolar: Mapped[float | None] = mapped_column(Numeric(18, 2))
    prioridad: Mapped[str | None] = mapped_column(String(60))
    categoria: Mapped[int | None] = mapped_column(SmallInteger)
    region: Mapped[str | None] = mapped_column(String(30))
    autorizada_2025: Mapped[str | None] = mapped_column(String(60))
    pit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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

    localidades: Mapped[list["GasPitObraLocalidad"]] = relationship(viewonly=True)


class GasPitObraLocalidad(Base):
    """Relación N:M obra<->localidad — LOCALIDAD en el Sheet suele traer 2+
    nombres concatenados (ej. "TANTI - EL DURAZNO")."""

    __tablename__ = "gas_pit_obras_localidades"
    __table_args__ = (UniqueConstraint("obra_id", "localidad", name="uq_gas_pit_obra_localidad"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    obra_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("gas_pit_obras.id", ondelete="CASCADE"), nullable=False
    )
    localidad: Mapped[str] = mapped_column(String(150), nullable=False)


class GasPitAccionTerritorio(Base):
    """Hito/acción de seguimiento territorial sincronizado desde 'ACCIONES
    TERRITORIO' (ya 100% Área = "Secretaría Gas")."""

    __tablename__ = "gas_pit_acciones_territorio"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fecha: Mapped[date | None] = mapped_column(Date)
    departamento: Mapped[str | None] = mapped_column(String(100))
    localidad: Mapped[str | None] = mapped_column(String(150))
    ministerio: Mapped[str | None] = mapped_column(String(150))
    area: Mapped[str | None] = mapped_column(String(150))
    id_accion: Mapped[str | None] = mapped_column(String(50))
    accion: Mapped[str | None] = mapped_column(String(200))
    detalle_accion: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(30), nullable=False)
    monto_inversion_solicitado: Mapped[float | None] = mapped_column(Numeric(18, 2))
    comentarios: Mapped[str | None] = mapped_column(Text)
    # Recalculado en el sync (monto_inversion_solicitado * settings.tipo_cambio_usd),
    # NUNCA leído de la hoja "monto actualizado " (acoplada por posición de fila —
    # antipatrón detectado en el análisis, ver spec §5.3).
    monto_inversion_usd: Mapped[float | None] = mapped_column(Numeric(18, 2))
    alerta_localidad: Mapped[str | None] = mapped_column(String(200))
    # Única clave natural razonable en esta hoja (no hay combinación de columnas de
    # negocio que garantice unicidad) — sensible a reordenamiento manual de filas en
    # el Sheet, riesgo aceptado y documentado en el spec (§6).
    sheet_row_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
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


class GasPitSyncLog(Base):
    """Una fila por corrida de sincronización (cubre las dos hojas juntas)."""

    __tablename__ = "gas_pit_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filas_leidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_insertadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_actualizadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errores: Mapped[str | None] = mapped_column(Text)  # JSON serializado (lista de {fila, hoja, motivo})
    triggered_by: Mapped[str | None] = mapped_column(String(50))
