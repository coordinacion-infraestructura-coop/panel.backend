import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GobAbiertoSyncLog(Base):
    """Una fila por corrida de la exportación a la planilla de Gobierno Abierto (append-only,
    mismo patrón que `viv_cc_sync_log`). Spec: spec-export-gobierno-abierto-vivienda.md §5."""

    __tablename__ = "viv_gobabierto_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    origen: Mapped[str] = mapped_column(String(20), nullable=False)  # 'hito' | 'scheduler' | 'manual'
