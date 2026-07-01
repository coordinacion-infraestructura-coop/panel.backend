import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EstadoCordonCuneta(Base):
    __tablename__ = "viv_cc_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    bg: Mapped[str] = mapped_column(String(10), nullable=False)
    text_color: Mapped[str] = mapped_column(String(10), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MunicipioCordonCuneta(Base):
    __tablename__ = "viv_cordon_cuneta"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    municipio: Mapped[str] = mapped_column(String(150), nullable=False)
    departamento: Mapped[str | None] = mapped_column(String(100))
    expediente: Mapped[str | None] = mapped_column(String(60))
    monto: Mapped[float | None] = mapped_column(Numeric(18, 2))
    ok_gob: Mapped[str] = mapped_column(String(20), nullable=False, default="SI")
    doc_exp: Mapped[str | None] = mapped_column(Text)
    ejuridico: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_cc_estados.id"))
    etecnico: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_cc_estados.id"))
    efinanciero: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("viv_cc_estados.id"))
    cordon_cuneta_ml: Mapped[float | None] = mapped_column(Numeric(10, 2))
    adoquinado_m2: Mapped[float | None] = mapped_column(Numeric(10, 2))
    obs: Mapped[str | None] = mapped_column(Text)
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


class ConfigCordonCuneta(Base):
    __tablename__ = "viv_cc_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    presupuesto: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
