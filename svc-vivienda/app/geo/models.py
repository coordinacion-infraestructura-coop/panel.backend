import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
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
    docs/files/spec-normalizacion-localidades.md §4.2 y
    docs/files/spec-geo-asignacion-manual-localidades.md §3.2.
    """

    __tablename__ = "viv_geo_alias_manual"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # normalize_name() del texto crudo tal cual aparece en la fuente (Sheet, alta manual, etc.)
    texto_normalizado: Mapped[str] = mapped_column(String(200), nullable=False)
    # normalize_departamento() del departamento al que se acota el alias; "" = alias
    # global, vale para cualquier departamento.
    departamento_normalizado: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default=""
    )
    texto_original: Mapped[str] = mapped_column(String(200), nullable=False)
    # NULL = "conocido pero ausente del padrón" (ej. Santiago Temple) — nunca se inventa un id_geo
    id_geo: Mapped[str | None] = mapped_column(String(20), ForeignKey("viv_geo_localidades.id_geo"))
    motivo: Mapped[str | None] = mapped_column(Text)
    origen: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # JSON con los registros de CC/CH/ML que tomaron el vínculo al crear el alias
    # y sus valores anteriores — de acá sale el "deshacer".
    propagacion: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "uq_geo_alias_manual_texto_departamento",
            "texto_normalizado", "departamento_normalizado",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )


class GeoPendiente(Base):
    """Localidad que alguna fuente mandó al resolver y no matcheó contra el
    padrón ni contra un alias. La mantiene `geo/service.py::resolver_lote`; un
    Admin la resuelve desde la pantalla de asignación manual. Ver
    docs/files/spec-geo-asignacion-manual-localidades.md §3.1.
    """

    __tablename__ = "viv_geo_pendientes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    origen: Mapped[str] = mapped_column(String(50), nullable=False)
    departamento_original: Mapped[str | None] = mapped_column(String(200))
    localidad_original: Mapped[str] = mapped_column(String(200), nullable=False)
    departamento_normalizado: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default=""
    )
    texto_normalizado: Mapped[str] = mapped_column(String(200), nullable=False)
    # Registros afectados en la última corrida que la informó. Para CC/CH/ML se
    # cuenta en vivo al listar (misma base), no se usa esta columna.
    cantidad: Mapped[int | None] = mapped_column(Integer)
    primera_vez: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    ultima_vez: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pendiente", server_default="pendiente"
    )
    alias_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("viv_geo_alias_manual.id"))
    resuelta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resuelta_by: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        Index(
            "uq_geo_pendientes_origen_departamento_texto",
            "origen", "departamento_normalizado", "texto_normalizado",
            unique=True,
        ),
    )
