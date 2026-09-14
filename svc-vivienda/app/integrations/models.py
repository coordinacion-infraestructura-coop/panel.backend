"""Vinculación Vivienda -> Privada (ADR-020, `docs/files/spec-vinculacion-vivienda-privada.md`).

`(caso_tipo, caso_id)` no lleva FK real — apunta a una de 3 tablas distintas según
`caso_tipo` (mismo patrón polimórfico que `ChecklistTecnico.programa`/`entidad_id`
en `app/checklist_tecnico/models.py`); `privada_sync.py` no valida la existencia de
la entidad porque siempre se llama desde dentro de `crear_*`/`actualizar_*`, con la
entidad ya persistida en la misma transacción.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VinculoPrivada(Base):
    """Snapshot: 1 fila por caso de Vivienda (CC/CH/ML) — estado ACTUAL del vínculo
    con su gestión de Privada (si lo hay). Se upsertea en cada sincronización."""

    __tablename__ = "viv_privada_vinculos"
    __table_args__ = (
        UniqueConstraint("caso_tipo", "caso_id", name="uq_privada_vinculo_caso"),
        CheckConstraint("caso_tipo IN ('cc','ch','ml')", name="ck_privada_vinculo_caso_tipo"),
        CheckConstraint(
            "estado_vinculo IN ('LINKED','PENDING_REVIEW','ERROR')", name="ck_privada_vinculo_estado"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    caso_tipo: Mapped[str] = mapped_column(String(2), nullable=False)
    caso_id: Mapped[str] = mapped_column(String(36), nullable=False)
    id_legacy: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    gestion_id: Mapped[str | None] = mapped_column(String(36))
    estado_vinculo: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING_REVIEW")
    motivo: Mapped[str | None] = mapped_column(String(60))

    ultimo_intento_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    ultimo_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class VinculoPrivadaSyncLog(Base):
    """Append-only: 1 fila por intento de sincronización (precedente: `viv_cc_sync_log`
    / `viv_informe_snapshot`, que insertan una fila por corrida). Log TÉCNICO — no es
    la alerta que ve el usuario (eso va al panel de notificaciones, `app/notificaciones/`,
    ver `privada_sync.py`); esto es trazabilidad de ingeniería (incluye los `ERROR`
    transitorios que jamás deberían llegar como alerta al usuario)."""

    __tablename__ = "viv_privada_sync_log"
    __table_args__ = (Index("ix_privada_sync_log_caso", "caso_tipo", "caso_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    caso_tipo: Mapped[str] = mapped_column(String(2), nullable=False)
    caso_id: Mapped[str] = mapped_column(String(36), nullable=False)
    id_legacy: Mapped[str] = mapped_column(String(100), nullable=False)

    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    gestion_id: Mapped[str | None] = mapped_column(String(36))
    motivo: Mapped[str | None] = mapped_column(String(60))
    diff_json: Mapped[dict | None] = mapped_column(JSON)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_detalle: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
