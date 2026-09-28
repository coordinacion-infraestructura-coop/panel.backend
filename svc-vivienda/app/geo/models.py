import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
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


class GeoAliasManual(Base):
    """Vinculación manual texto crudo → `id_geo`, centraliza lo que antes vivía
    hardcodeado en `frontend/AtpPage.tsx` (`VINCULACION_MANUAL`). Ver
    docs/files/spec-normalizacion-localidades.md §4.2.
    """

    __tablename__ = "viv_geo_alias_manual"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # normalize_name() del texto crudo tal cual aparece en la fuente (Sheet, alta manual, etc.)
    texto_normalizado: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    texto_original: Mapped[str] = mapped_column(String(200), nullable=False)
    # NULL = "conocido pero ausente del padrón" (ej. Santiago Temple) — nunca se inventa un id_geo
    id_geo: Mapped[str | None] = mapped_column(String(20), ForeignKey("viv_geo_localidades.id_geo"))
    motivo: Mapped[str | None] = mapped_column(Text)
    origen: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
