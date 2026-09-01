"""Datos de referencia territorial (ADR-012).

Propiedad de svc-privada, expuestos read-only vía gateway a otros servicios
(resumen_territorial de svc-vivienda). El `PUT /localidades-info` sólo edita
habitantes/electores/intendente_jefe_comunal/partido_politico — `tipo_localidad`
y `color_semaforo` vienen de una carga Excel one-off y son read-only desde la app.
`priv_departamentos_info` es read-only completo.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LocalidadInfo(Base):
    __tablename__ = "priv_localidades_info"

    departamento: Mapped[str] = mapped_column(String(120), primary_key=True)
    localidad: Mapped[str] = mapped_column(String(160), primary_key=True)
    habitantes: Mapped[int | None] = mapped_column(Integer)
    electores: Mapped[int | None] = mapped_column(Integer)
    intendente_jefe_comunal: Mapped[str | None] = mapped_column(String(200))
    partido_politico: Mapped[str | None] = mapped_column(String(200))
    tipo_localidad: Mapped[str | None] = mapped_column(String(60))
    color_semaforo: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(200))


class DepartamentoInfo(Base):
    __tablename__ = "priv_departamentos_info"

    departamento: Mapped[str] = mapped_column(String(120), primary_key=True)
    habitantes: Mapped[int | None] = mapped_column(Integer)
    electores: Mapped[int | None] = mapped_column(Integer)
    legislador_departamental: Mapped[str | None] = mapped_column(String(200))
    partido_politico: Mapped[str | None] = mapped_column(String(200))
    legislador_sabana1: Mapped[str | None] = mapped_column(String(200))
    partido_politico_sabana1: Mapped[str | None] = mapped_column(String(200))
    legislador_sabana2: Mapped[str | None] = mapped_column(String(200))
    partido_politico_sabana2: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(200))


class GeoLocalidad(Base):
    __tablename__ = "priv_geo_localidades"

    id_geo: Mapped[str] = mapped_column(String(30), primary_key=True)
    departamento: Mapped[str] = mapped_column(String(120), nullable=False)
    localidad: Mapped[str] = mapped_column(String(200), nullable=False)
    # renombrados desde lat_centro/lon_centro del origen (spec §5)
    lat: Mapped[float | None] = mapped_column(Numeric(12, 7))
    lon: Mapped[float | None] = mapped_column(Numeric(12, 7))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
