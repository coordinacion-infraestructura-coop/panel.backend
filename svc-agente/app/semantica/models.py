"""Capa semántica (schema `ag`) — spec-agente-consultas.md §3.

Proyección de solo lectura de las cinco bases operativas, recargada completa en cada refresco
(app/etl/carga.py). Todas las filas llevan `id_geo` + departamento/localidad OFICIALES del padrón
cuando la fuente trae vínculo (ADR-024/026); si no, el texto de origen.

Estas tablas son lo único que ve `consulta_sql` (rol `agente_llm`). Ningún dato personal llega
acá (spec §4): los extractores no seleccionan esas columnas y el rol `agente_ro` no puede leerlas.
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

AG = {"schema": "ag"}


class AgLocalidad(Base):
    __tablename__ = "ag_localidades"
    __table_args__ = AG

    id_geo: Mapped[str] = mapped_column(String(30), primary_key=True)
    localidad: Mapped[str] = mapped_column(String(160))
    departamento: Mapped[str] = mapped_column(String(120))
    poblacion: Mapped[int | None] = mapped_column(Integer)
    viviendas: Mapped[int | None] = mapped_column(Integer)
    intendente: Mapped[str | None] = mapped_column(String(200))
    partido: Mapped[str | None] = mapped_column(String(200))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    url_ficha: Mapped[str | None] = mapped_column(String(400))


class AgAlias(Base):
    """Espejo de `viv_geo_alias_manual` para resolver texto del usuario (spec §3.1)."""

    __tablename__ = "ag_alias"
    __table_args__ = AG

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    texto_normalizado: Mapped[str] = mapped_column(String(200))
    departamento_normalizado: Mapped[str] = mapped_column(String(120))
    id_geo: Mapped[str | None] = mapped_column(String(30))


class AgProgramaItem(Base):
    """Una fila por convenio/proyecto/obra/compromiso y localidad.

    Obras de Gasífera con varias localidades: una fila por localidad con el monto prorrateado
    en partes iguales, para que la suma por territorio no duplique (`origen_id` es la obra)."""

    __tablename__ = "ag_programa_items"
    __table_args__ = AG

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    programa: Mapped[str] = mapped_column(String(20))  # cc | ch | ml | gas_obra | gas_accion | atp
    programa_nombre: Mapped[str] = mapped_column(String(80))
    secretaria: Mapped[str] = mapped_column(String(40))
    origen_id: Mapped[str] = mapped_column(String(60))
    nombre: Mapped[str | None] = mapped_column(String(300))
    id_geo: Mapped[str | None] = mapped_column(String(30))
    departamento: Mapped[str | None] = mapped_column(String(120))
    localidad: Mapped[str | None] = mapped_column(String(160))
    estado_origen: Mapped[str | None] = mapped_column(String(300))
    estado_normalizado: Mapped[str] = mapped_column(String(30))
    estado_tecnico: Mapped[str | None] = mapped_column(String(120))
    avance: Mapped[float | None] = mapped_column(Float)  # 0..1
    cantidad: Mapped[int | None] = mapped_column(Integer)  # viviendas (CH) / lotes (ML)
    monto: Mapped[float | None] = mapped_column(Float)  # pesos
    monto_ejecutado: Mapped[float | None] = mapped_column(Float)  # pesos, según glosario
    monto_usd: Mapped[float | None] = mapped_column(Float)  # Gasífera, nunca se suma a pesos
    fecha_inicio: Mapped[date | None] = mapped_column(Date)
    fecha_ultimo_cambio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    url: Mapped[str | None] = mapped_column(String(400))


class AgGestion(Base):
    __tablename__ = "ag_gestiones"
    __table_args__ = AG

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    estado: Mapped[str] = mapped_column(String(60))
    estado_normalizado: Mapped[str] = mapped_column(String(30))
    urgencia: Mapped[str | None] = mapped_column(String(30))
    area: Mapped[str | None] = mapped_column(String(200))
    ministerio: Mapped[str | None] = mapped_column(String(200))
    categoria: Mapped[str | None] = mapped_column(String(200))
    categoria_general: Mapped[str | None] = mapped_column(String(200))
    programa: Mapped[str | None] = mapped_column(String(200))
    tipo_gestion: Mapped[str | None] = mapped_column(String(120))
    canal_origen: Mapped[str | None] = mapped_column(String(120))
    id_geo: Mapped[str | None] = mapped_column(String(30))
    departamento: Mapped[str | None] = mapped_column(String(120))
    localidad: Mapped[str | None] = mapped_column(String(200))
    fecha_ingreso: Mapped[date | None] = mapped_column(Date)
    fecha_estado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_finalizacion: Mapped[date | None] = mapped_column(Date)
    dias_abierta: Mapped[int | None] = mapped_column(Integer)  # NULL si está cerrada
    ok_gobernador: Mapped[str | None] = mapped_column(String(20))
    ok_ministro: Mapped[str | None] = mapped_column(String(20))
    costo_estimado: Mapped[float | None] = mapped_column(Float)
    detalle: Mapped[str | None] = mapped_column(Text)  # enmascarado (spec §4)


class AgMovimiento(Base):
    __tablename__ = "ag_movimientos"
    __table_args__ = AG

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    programa: Mapped[str] = mapped_column(String(20))
    origen_id: Mapped[str] = mapped_column(String(60))
    id_geo: Mapped[str | None] = mapped_column(String(30))
    dimension: Mapped[str] = mapped_column(String(30))  # juridico | financiero | tecnico | estado
    estado_anterior: Mapped[str | None] = mapped_column(String(300))
    estado_nuevo: Mapped[str | None] = mapped_column(String(300))
    fecha: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgHito(Base):
    __tablename__ = "ag_hitos"
    __table_args__ = AG

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    programa: Mapped[str] = mapped_column(String(20))
    origen_id: Mapped[str] = mapped_column(String(60))
    id_geo: Mapped[str | None] = mapped_column(String(30))
    hito: Mapped[str] = mapped_column(String(40))
    porcentaje: Mapped[float] = mapped_column(Float)
    monto: Mapped[float | None] = mapped_column(Float)
    fecha_acreditado: Mapped[date | None] = mapped_column(Date)


class AgTransferencia(Base):
    __tablename__ = "ag_transferencias"
    __table_args__ = AG

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id_geo: Mapped[str | None] = mapped_column(String(30))
    departamento: Mapped[str | None] = mapped_column(String(120))
    localidad: Mapped[str | None] = mapped_column(String(200))
    tipo: Mapped[str | None] = mapped_column(String(10))  # municipio | comuna
    concepto: Mapped[str] = mapped_column(String(50))
    periodo: Mapped[date] = mapped_column(Date)
    monto: Mapped[float] = mapped_column(Float)


class AgAtpPago(Base):
    """ATP Compromisos y ATP Interno van separados y NUNCA se suman (ADR-029, act. 2026-10-13)."""

    __tablename__ = "ag_atp_pagos"
    __table_args__ = AG

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fuente: Mapped[str] = mapped_column(String(20))  # compromiso | interno
    origen_id: Mapped[str | None] = mapped_column(String(60))
    id_geo: Mapped[str | None] = mapped_column(String(30))
    departamento: Mapped[str | None] = mapped_column(String(120))
    localidad: Mapped[str | None] = mapped_column(String(200))
    fecha: Mapped[date | None] = mapped_column(Date)
    monto: Mapped[float] = mapped_column(Float)


class AgFrescura(Base):
    __tablename__ = "ag_frescura"
    __table_args__ = AG

    fuente: Mapped[str] = mapped_column(String(40), primary_key=True)
    estado: Mapped[str] = mapped_column(String(20))  # ok | error | sin_configurar
    filas: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_dato: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refrescado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mensaje: Mapped[str | None] = mapped_column(Text)


TABLAS_AG = (
    AgLocalidad, AgAlias, AgProgramaItem, AgGestion, AgMovimiento,
    AgHito, AgTransferencia, AgAtpPago, AgFrescura,
)
NOMBRES_TABLAS_AG = frozenset(t.__tablename__ for t in TABLAS_AG)
