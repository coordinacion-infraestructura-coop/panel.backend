"""Espejos de solo lectura de las planillas de gestión territorial de Gobierno
(spec-datos-externos-fase5-gestion-territorial.md §2).

Misma excepción documentada que las Fases 2 y 3: sin `deleted_at`, porque cada corrida reemplaza
la tabla completa de su fuente; la historia queda en `ext_gob_sync_log`. Códigos sin FK al
nomenclador.

No hay lugar para intendente, partido, firmantes, detalle de reuniones ni tema o institución de
las visitas: el sync no lee esas columnas (spec §5).
"""
from datetime import date

from sqlalchemy import JSON, Boolean, Date, Float, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.gob_transferencias.models import _Timestamps


class ExtGobObra(_Timestamps, Base):
    """"12. Obras", pestaña `BD-TABLERO`: una fila por obra y localidad."""

    __tablename__ = "ext_gob_obra"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_obra: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)  # NULL: provincial o zona rural
    codigo_zona_rural: Mapped[str | None] = mapped_column(String(10))  # `nnZR`
    ambito: Mapped[str | None] = mapped_column(String(40))  # UNICA / COMPARTIDA - DPTO UNICO / COMPARTIDA / PROVINCIAL
    localidad: Mapped[str | None] = mapped_column(String(150))
    departamento: Mapped[str | None] = mapped_column(String(100))
    nombre: Mapped[str | None] = mapped_column(Text)
    division: Mapped[str | None] = mapped_column(String(60))
    estado: Mapped[str | None] = mapped_column(String(60))
    categoria: Mapped[str | None] = mapped_column(String(60))
    avance: Mapped[float | None] = mapped_column(Float)  # 0–1
    fecha_inicio: Mapped[date | None] = mapped_column(Date)
    fecha_fin: Mapped[date | None] = mapped_column(Date)
    # Se guarda y no se expone hasta que el área confirme la moneda (spec §0).
    monto: Mapped[float | None] = mapped_column(Numeric(18, 2))


class ExtGobVisita(_Timestamps, Base):
    """`Recorrido` de las planillas 2 (`origen = funcionarios`) y 2.1 (`origen = ministro`)."""

    __tablename__ = "ext_gob_visita"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    origen: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    funcionario: Mapped[str | None] = mapped_column(String(120))
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    localidad: Mapped[str | None] = mapped_column(String(150))
    departamento: Mapped[str | None] = mapped_column(String(100))
    tipo: Mapped[str | None] = mapped_column(String(80))


class ExtGobVisitaGobernador(_Timestamps, Base):
    """`Visitas Gober`: una fila por gobierno local."""

    __tablename__ = "ext_gob_visita_gobernador"

    codigo_indec: Mapped[str] = mapped_column(String(20), primary_key=True)
    visitada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fecha_ultima: Mapped[date | None] = mapped_column(Date)
    rango_habitantes: Mapped[str | None] = mapped_column(String(40))


class ExtGobReunion(_Timestamps, Base):
    """"1. REGISTRO REUNIONES", pestaña `Reuniones`. Sin detalle (spec §5)."""

    __tablename__ = "ext_gob_reunion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_reu: Mapped[int | None] = mapped_column(Integer)
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)
    codigo_zona_rural: Mapped[str | None] = mapped_column(String(10))
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    temas: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    resolucion: Mapped[str | None] = mapped_column(String(40))


class ExtGobConvenio(_Timestamps, Base):
    """"6. CONVENIOS FIRMADOS Y RADIOS", pestaña `Convenios`, en formato largo: una fila por
    localidad y convenio, así una columna nueva entra sin migración."""

    __tablename__ = "ext_gob_convenio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    convenio: Mapped[str] = mapped_column(String(60), nullable=False)
    valor: Mapped[str | None] = mapped_column(String(10))  # SI / NO / NC
    cantidad: Mapped[int | None] = mapped_column(Integer)  # polideportivos, parques industriales
    detalle: Mapped[str | None] = mapped_column(String(40))  # año de la radio
