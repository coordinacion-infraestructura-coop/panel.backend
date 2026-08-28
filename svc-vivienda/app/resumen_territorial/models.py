import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResumenTerritorialSnapshot(Base):
    """Una fila por corrida de cálculo del Resumen Territorial.

    No se sobreescribe — se guarda historial completo (mismo criterio que
    viv_informe_snapshot / viv_cc_sync_log) y se lee la última por
    `computed_at DESC`. El `payload` guarda el resumen COMPLETO, sin filtrar
    por visibilidad — el filtro por área/rol se aplica en el GET.

    Spec: docs/files/spec-resumen-territorial.md §5.1
    """

    __tablename__ = "viv_resumen_territorial_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    computed_by: Mapped[str | None] = mapped_column(String(255))
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
