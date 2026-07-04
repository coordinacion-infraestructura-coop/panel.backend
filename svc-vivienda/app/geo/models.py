from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoLocalidad(Base):
    __tablename__ = "viv_geo_localidades"

    id_geo: Mapped[str] = mapped_column(String(20), primary_key=True)
    departamento: Mapped[str] = mapped_column(String(100), nullable=False)
    localidad: Mapped[str] = mapped_column(String(150), nullable=False)
    lat_centro: Mapped[float | None] = mapped_column(Numeric(10, 7))
    lon_centro: Mapped[float | None] = mapped_column(Numeric(10, 7))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
