import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InformeSnapshot(Base):
    """Una fila por corrida de cálculo del informe de un programa (CC, CH, ...).

    No se sobreescribe — se guarda historial completo (mismo criterio que
    viv_cc_sync_log) y se lee la última por (programa, computed_at DESC).
    """

    __tablename__ = "viv_informe_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    programa: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    computed_by: Mapped[str | None] = mapped_column(String(255))
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
