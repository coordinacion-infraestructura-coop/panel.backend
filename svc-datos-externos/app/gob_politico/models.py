"""Espejos de solo lectura del padrón de intendentes y de los resultados electorales
(spec-datos-externos-fase6-politico.md §2).

Misma excepción documentada que las Fases 2 a 5: sin `deleted_at`, porque cada corrida reemplaza
la tabla completa de su fuente; la historia queda en `ext_gob_sync_log`. Códigos sin FK al
nomenclador.

Todo es dato político (y `celular`, dato personal): solo lo leen los roles `Admin` y `Autoridad`
por el tablero, nunca el rollup ni los logs (spec §5).
"""
from datetime import date

from sqlalchemy import JSON, Boolean, Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.gob_transferencias.models import _Timestamps


class ExtGobIntendente(_Timestamps, Base):
    """"1. REGISTRO REUNIONES", pestaña `Intendentes`: una fila por gobierno local."""

    __tablename__ = "ext_gob_intendente"

    codigo_indec: Mapped[str] = mapped_column(String(20), primary_key=True)
    intendente: Mapped[str | None] = mapped_column(String(150))
    reelecto: Mapped[bool | None] = mapped_column(Boolean)
    partido: Mapped[str | None] = mapped_column(String(150))
    continuidad: Mapped[bool | None] = mapped_column(Boolean)
    celular: Mapped[str | None] = mapped_column(String(30))  # dato personal (spec §5)
    foto_url: Mapped[str | None] = mapped_column(String(500))


class ExtGobEleccionCircuito(_Timestamps, Base):
    """Pestañas `2025`, `2023` y `2021` de la planilla 18: una fila por elección y circuito. Las
    fuerzas cambian entre elecciones, así que van en `votos` (fuerza -> votos)."""

    __tablename__ = "ext_gob_eleccion_circuito"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eleccion: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    circuito_id: Mapped[str] = mapped_column(String(20), nullable=False)
    circuito_nombre: Mapped[str | None] = mapped_column(String(150))
    departamento: Mapped[str | None] = mapped_column(String(100))
    padron: Mapped[int | None] = mapped_column(Integer)
    mesas: Mapped[int | None] = mapped_column(Integer)
    nulos: Mapped[int | None] = mapped_column(Integer)
    blancos: Mapped[int | None] = mapped_column(Integer)
    impugnados: Mapped[int | None] = mapped_column(Integer)
    recurridos: Mapped[int | None] = mapped_column(Integer)
    total_votos: Mapped[int | None] = mapped_column(Integer)
    afirmativos: Mapped[int | None] = mapped_column(Integer)
    validos: Mapped[int | None] = mapped_column(Integer)
    votos: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ExtGobCircuitoLocalidad(_Timestamps, Base):
    """`RESUMEN_VOTOS_CIRCUITOS`: a qué localidad pertenece cada circuito. La planilla nombra la
    localidad; el código se resuelve contra el nomenclador después del sync."""

    __tablename__ = "ext_gob_circuito_localidad"

    circuito_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    localidad: Mapped[str] = mapped_column(String(150), nullable=False)
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)


class ExtGobEleccionMunicipal(_Timestamps, Base):
    """`Municipales - 2023`: ganador y segundo de cada gobierno local."""

    __tablename__ = "ext_gob_eleccion_municipal"

    codigo_indec: Mapped[str] = mapped_column(String(20), primary_key=True)
    periodo: Mapped[str | None] = mapped_column(String(20))
    tipo_gobierno: Mapped[str | None] = mapped_column(String(40))
    fecha: Mapped[date | None] = mapped_column(Date)
    participacion: Mapped[float | None] = mapped_column(Float)
    afirmativos: Mapped[int | None] = mapped_column(Integer)
    padron: Mapped[int | None] = mapped_column(Integer)
    ganador_partido: Mapped[str | None] = mapped_column(String(200))
    ganador_partido_norm: Mapped[str | None] = mapped_column(String(100))
    ganador_votos: Mapped[int | None] = mapped_column(Integer)
    ganador_pct: Mapped[float | None] = mapped_column(Float)
    ganador_nombre: Mapped[str | None] = mapped_column(String(150))
    ganador_sexo: Mapped[str | None] = mapped_column(String(10))
    segundo_partido: Mapped[str | None] = mapped_column(String(200))
    segundo_partido_norm: Mapped[str | None] = mapped_column(String(100))
    segundo_votos: Mapped[int | None] = mapped_column(Integer)
    segundo_pct: Mapped[float | None] = mapped_column(Float)
    segundo_nombre: Mapped[str | None] = mapped_column(String(150))
    otras_votos: Mapped[int | None] = mapped_column(Integer)
    otras_pct: Mapped[float | None] = mapped_column(Float)


class ExtGobEleccionCopia(_Timestamps, Base):
    """Pestañas pegadas de la planilla 18 (`RESULTADOS CALVO`, `GANADORES`, `RESUMEN_VOTOS`), una
    fila por pestaña y localidad. Se usan para lo que no tiene base (gobernador 2023, alineación)
    y para comparar contra el recálculo (spec §3.3). Sin intendente ni partido: no se leen."""

    __tablename__ = "ext_gob_eleccion_copia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pestana: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    localidad: Mapped[str] = mapped_column(String(150), nullable=False)
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)
    datos: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
