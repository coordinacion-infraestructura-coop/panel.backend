"""Planificación de programas por localidad (spec-privada-planificacion-programas.md / ADR-036).

Privada es dueña de la prioridad, el estado, el OK del gobernador y los valores de columnas
configurables por (programa, localidad), y de los catálogos de prioridades, estados y columnas
**por programa**. Lo que ya existe en el panel de cada programa (CC/CH/ML/Gasífera/ATP) se lee
de su servicio por IAM; nunca se escribe ahí.

Soft delete universal (`deleted_at`). Un catálogo borrado se sigue mostrando en las filas que
lo tienen ("(eliminado)") hasta que alguien lo cambie — nunca se reasigna en silencio (§4.3).
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# JSONB en Postgres, JSON en SQLite (tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class _Auditada(Base):
    __abstract__ = True

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanPrograma(_Auditada):
    __tablename__ = "priv_plan_programas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    area: Mapped[str] = mapped_column(String(40), nullable=False)
    # Vínculo con un panel existente (§4.1); NULL = programa sólo de planificación.
    fuente: Mapped[str | None] = mapped_column(String(40))
    descripcion: Mapped[str | None] = mapped_column(Text)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class PlanEstado(_Auditada):
    __tablename__ = "priv_plan_estados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    programa_id: Mapped[int] = mapped_column(ForeignKey("priv_plan_programas.id"), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    color_bg: Mapped[str | None] = mapped_column(String(9))
    color_texto: Mapped[str | None] = mapped_column(String(9))
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class PlanPrioridad(_Auditada):
    __tablename__ = "priv_plan_prioridades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    programa_id: Mapped[int] = mapped_column(ForeignKey("priv_plan_programas.id"), nullable=False, index=True)
    codigo: Mapped[str] = mapped_column(String(10), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    color_bg: Mapped[str | None] = mapped_column(String(9))
    color_texto: Mapped[str | None] = mapped_column(String(9))
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # "Desestimado": se ordena al final y se puede ocultar con un filtro.
    excluye: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class PlanColumna(_Auditada):
    __tablename__ = "priv_plan_columnas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    programa_id: Mapped[int] = mapped_column(ForeignKey("priv_plan_programas.id"), nullable=False, index=True)
    # Slug estable: se genera del nombre al crear y no cambia al renombrar (es la clave en `valores`).
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    opciones: Mapped[list | None] = mapped_column(JsonType)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class PlanLocalidad(_Auditada):
    __tablename__ = "priv_plan_localidad"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    programa_id: Mapped[int] = mapped_column(ForeignKey("priv_plan_programas.id"), nullable=False, index=True)
    id_geo: Mapped[str] = mapped_column(ForeignKey("priv_geo_localidades.id_geo"), nullable=False)
    prioridad_id: Mapped[int | None] = mapped_column(ForeignKey("priv_plan_prioridades.id"))
    estado_id: Mapped[int | None] = mapped_column(ForeignKey("priv_plan_estados.id"))
    ok_gobernador: Mapped[bool | None] = mapped_column(Boolean)
    valores: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)


class PlanHistorial(Base):
    """Historial legible en pantalla (§4.6). Append-only; duplica a propósito una parte de
    `priv_audit_log` — aquél es para auditoría, éste para la columna desplegable."""

    __tablename__ = "priv_plan_historial"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    programa_id: Mapped[int] = mapped_column(ForeignKey("priv_plan_programas.id"), nullable=False)
    id_geo: Mapped[str] = mapped_column(String(30), nullable=False)
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    valor_anterior: Mapped[str | None] = mapped_column(Text)
    valor_nuevo: Mapped[str | None] = mapped_column(Text)
    usuario: Mapped[str | None] = mapped_column(String(200))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
