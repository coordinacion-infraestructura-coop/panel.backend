from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExtGeoCenso(Base):
    """Censo 2022 INDEC a nivel gobierno local — carga única (no recurrente),
    ver spec-resumen-territorial-tablero-v2.md §2.1/§2.2. Fuente:
    docs/data/c2022_cordoba_gobierno_local_c1 (5).xlsx, hoja "Cuadro 1.6".

    `id_geo` es texto, resuelto contra `viv_geo_localidades` (ADR-024) en la
    migración de carga — sin FK real (cross-DB, mismo criterio que el resto
    de las tablas que vinculan por `id_geo`).

    El "Cuadro 1.6" del Censo NO trae departamento — solo "Jurisdicción"
    (siempre "Córdoba", la provincia) y "Gobierno local" (nombre de
    localidad). `departamento_censo` se backfillea desde la localidad de
    `viv_geo_localidades` que matcheó, cuando matcheó — nunca se fabrica un
    valor si `id_geo` quedó NULL.
    """

    __tablename__ = "ext_geo_censo"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id_geo: Mapped[str | None] = mapped_column(String(20))
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    categoria: Mapped[str] = mapped_column(String(2), nullable=False)  # "MU" | "CO"
    departamento_censo: Mapped[str | None] = mapped_column(String(100))
    localidad_censo: Mapped[str] = mapped_column(String(150), nullable=False)
    poblacion_2022: Mapped[int | None] = mapped_column(Integer)
    viviendas_2022: Mapped[int | None] = mapped_column(Integer)
    match_tipo: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
