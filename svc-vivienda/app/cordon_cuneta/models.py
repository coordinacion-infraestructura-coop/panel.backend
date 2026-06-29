import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MunicipioCordonCuneta(Base):
    """
    Registra el estado de cada municipio en el Programa Cordón Cuneta.
    Migrado del Panel_Cordon_Cuneta.html (46 municipios con datos hardcodeados).
    """
    __tablename__ = "viv_cordon_cuneta"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    municipio: Mapped[str] = mapped_column(String(150), nullable=False)
    departamento: Mapped[str | None] = mapped_column(String(100))
    numero_expediente: Mapped[str | None] = mapped_column(String(50))
    monto: Mapped[float | None] = mapped_column(Numeric(16, 2))
    cordon_cuneta_ml: Mapped[float | None] = mapped_column(Numeric(10, 2), comment="Metros lineales")
    adoquinado_m2: Mapped[float | None] = mapped_column(Numeric(10, 2), comment="Metros cuadrados")

    # Estados del proceso
    est_documentacion: Mapped[str | None] = mapped_column(String(100))
    est_juridico_adm: Mapped[str | None] = mapped_column(String(100))
    est_tecnico: Mapped[str | None] = mapped_column(String(100))
    est_presup_fin: Mapped[str | None] = mapped_column(String(100))

    ok_ministerio: Mapped[bool] = mapped_column(default=False, nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text)

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
