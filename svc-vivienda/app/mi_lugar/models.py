import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EstadoML(Base):
    __tablename__ = "viv_ml_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(300))
    bg: Mapped[str] = mapped_column(String(10))
    text_color: Mapped[str] = mapped_column(String(10))
    orden: Mapped[int] = mapped_column(Integer)
    aplica_juridico: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    aplica_tecnico: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    aplica_financiero: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class ProyectoML(Base):
    __tablename__ = "viv_ml_proyectos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tipo: Mapped[str] = mapped_column(String(10))  # 'exp'|'muni'|'prov' — sin CHECK constraint
    nombre: Mapped[str] = mapped_column(String(200))
    localidad_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("viv_geo_localidades.id_geo"))
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
