import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EstadoML(Base):
    __tablename__ = "viv_ml_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(300))
    bg: Mapped[str] = mapped_column(String(10))
    text_color: Mapped[str] = mapped_column(String(10))
    orden: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, server_default="exp")
    aplica_juridico: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    aplica_tecnico: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    aplica_financiero: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # juridica | tecnica | financiera | externa — qué área lleva el estado (spec-vivienda-tablero-analitico §4.4)
    area_responsable: Mapped[str | None] = mapped_column(String(20), nullable=True)


class ProyectoML(Base):
    __tablename__ = "viv_ml_proyectos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tipo: Mapped[str] = mapped_column(String(10))  # 'exp'|'muni'|'prov' — sin CHECK constraint
    nombre: Mapped[str] = mapped_column(String(200))
    localidad_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("viv_geo_localidades.id_geo"))
    # Poblado por backfill (spec-normalizacion-localidades.md §4.9, ADR-024) para las
    # filas resueltas después del hecho — el alta/edición de ML no lo setea todavía
    # (fuera de alcance de esa spec, ver §2 excluido).
    localidad_match_tipo: Mapped[str | None] = mapped_column(String(20))
    localidad_nombre: Mapped[str] = mapped_column(String(150))
    departamento: Mapped[str | None] = mapped_column(String(100))
    expediente: Mapped[str | None] = mapped_column(String(80))
    responsable: Mapped[str | None] = mapped_column(String(150))
    superficie: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # Ha
    lotes: Mapped[int | None] = mapped_column(Integer)
    monto: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    valor_fiscal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # solo EXP
    infra_sin_nexos: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # EXP + PROV
    costo_nexos: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    convenio_unc: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    costo_total_infra: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ok_gob: Mapped[str] = mapped_column(String(20), server_default="SI")
    ejuridico: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_ml_estados.id"))
    etecnico: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_ml_estados.id"))
    efinanciero: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_ml_estados.id"))
    estado_general: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("viv_ml_estados.id", name="fk_ml_estado_general")
    )
    obs: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(String(255))


class GeoPuntoML(Base):
    __tablename__ = "viv_ml_geo_puntos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_ml_proyectos.id", ondelete="CASCADE"), nullable=False
    )
    lat: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    lng: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False)


class EstadoHistorialML(Base):
    __tablename__ = "viv_ml_estado_historial"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_ml_proyectos.id", ondelete="CASCADE"), nullable=False
    )
    campo: Mapped[str] = mapped_column(String(30), nullable=False)
    estado_anterior_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_ml_estados.id"))
    estado_nuevo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("viv_ml_estados.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(255))


class ConfigML(Base):
    __tablename__ = "viv_ml_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo_cambio: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default="1450")
    usd_por_lote: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default="10000")
    lotes_por_ha: Mapped[Decimal] = mapped_column(Numeric(8, 4), server_default="25")
    monto_por_lote_muni: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default="14000000")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PedidoML(Base):
    __tablename__ = "viv_ml_pedidos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_ml_proyectos.id", ondelete="CASCADE")
    )
    descripcion: Mapped[str] = mapped_column(Text)
    fecha_pedido: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_by_nombre: Mapped[str | None] = mapped_column(String(255))
    secretaria: Mapped[str | None] = mapped_column(String(100))
    # Corrección de la observación (spec-checklist-tecnico-dgv.md v1.7.0 §6-ter.2, migración 0041).
    editado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    editado_por: Mapped[str | None] = mapped_column(String(200))
    editado_por_nombre: Mapped[str | None] = mapped_column(String(255))


class NomenclaturaML(Base):
    """Nomenclaturas catastrales que carga el área por proyecto, además de los
    puntos (spec-mi-lugar-valor-fiscal-idecor.md §5.2, migración 0043)."""

    __tablename__ = "viv_ml_nomenclaturas"
    __table_args__ = (
        Index(
            "uq_ml_nomenclaturas_activas", "proyecto_id", "nomenclatura", unique=True,
            postgresql_where=text("deleted_at IS NULL"), sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_ml_proyectos.id", ondelete="CASCADE"), nullable=False
    )
    nomenclatura: Mapped[str] = mapped_column(String(30), nullable=False)  # solo dígitos
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(255))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ValuacionIdecorML(Base):
    """Último resultado de la consulta a IDECOR por proyecto: valor fiscal
    sugerido y valor de referencia de mercado. Solo referencia — nunca se copia
    sola a `ProyectoML.valor_fiscal` (spec-mi-lugar-valor-fiscal-idecor.md §5.2,
    ADR-031). Un error no pisa el último resultado bueno."""

    __tablename__ = "viv_ml_valuacion_idecor"

    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_ml_proyectos.id", ondelete="CASCADE"), primary_key=True
    )
    # ok | parcial | sin_datos | sin_parcelas | error
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    valor_tierra: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    valor_mejoras: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    valor_mercado: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    mercado_anio: Mapped[int | None] = mapped_column(Integer)
    mercado_parcelas_sin_valor: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cant_parcelas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    puntos_sin_parcela: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    nomenclaturas_no_encontradas: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")  # JSON
    vigencia_desde: Mapped[date | None] = mapped_column(Date)
    parcelas: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")  # JSON
    consultado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    ultimo_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
