import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EstadoCordobaHogar(Base):
    __tablename__ = "viv_ch_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(300))
    bg: Mapped[str] = mapped_column(String(10))
    text_color: Mapped[str] = mapped_column(String(10))
    orden: Mapped[int] = mapped_column(Integer)


class LocalidadCordobaHogar(Base):
    __tablename__ = "viv_cordoba_hogar"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    orden: Mapped[int] = mapped_column(Integer)
    localidad: Mapped[str] = mapped_column(String(150))
    departamento: Mapped[str | None] = mapped_column(String(100))
    fecha_anuncio: Mapped[date | None] = mapped_column(Date)
    expediente: Mapped[str | None] = mapped_column(String(60))
    monto: Mapped[float | None] = mapped_column(Numeric(18, 2))
    cantidad_casas: Mapped[int | None] = mapped_column(Integer)
    ok_gob: Mapped[str] = mapped_column(String(20), server_default="SI")
    doc_exp: Mapped[str | None] = mapped_column(Text)
    ejuridico: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_ch_estados.id"))
    etecnico: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_ch_estados.id"))
    efinanciero: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_ch_estados.id"))
    obs: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(String(255))


class ConfigCordobaHogar(Base):
    __tablename__ = "viv_ch_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    presupuesto: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PedidoCordobaHogar(Base):
    __tablename__ = "viv_ch_pedidos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    localidad_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viv_cordoba_hogar.id", ondelete="CASCADE")
    )
    descripcion: Mapped[str] = mapped_column(Text)
    fecha_pedido: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(255))
