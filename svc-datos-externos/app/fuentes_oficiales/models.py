"""Fuentes oficiales públicas por gobierno local: Estadística Córdoba (ArcGIS),
IDECOR (WFS) y RENABAP (vía Poblaciones).

Spec: docs/files/spec-datos-externos-fuentes-oficiales.md §3. Las tablas son un
espejo de la fuente: cada corrida buena reemplaza el contenido de su fuente;
una corrida fallida no toca lo que había. Por eso no hay soft delete.

Clave común: código INDEC de gobierno local de 6 dígitos, el mismo de
`ext_geo_censo` y `ext_gob_localidades`. El vínculo con el padrón (`id_geo`) se
resuelve en el rollup a través de `ext_gob_localidades`.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ExtEstGobiernoLocal(Base):
    """Indicadores del Censo 2022 (y población 2010 sobre límites 2022) e IPS
    por gobierno local — Estadística Córdoba, spec §3.1."""

    __tablename__ = "ext_est_gobierno_local"

    codigo_indec: Mapped[str] = mapped_column(String(10), primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(150))
    codigo_dpto_indec: Mapped[str | None] = mapped_column(String(10))
    tipo_2022: Mapped[str | None] = mapped_column(String(10))  # "MUN" | "COM"

    # Demografía (FichaGral)
    poblacion_2010: Mapped[int | None] = mapped_column(Integer)
    poblacion_2022: Mapped[int | None] = mapped_column(Integer)
    variacion_intercensal: Mapped[float | None] = mapped_column(Float)  # fracción: 0.61 = 61%
    superficie_km2: Mapped[float | None] = mapped_column(Numeric(12, 4))
    densidad: Mapped[float | None] = mapped_column(Float)
    hogares: Mapped[int | None] = mapped_column(Integer)
    personas_por_hogar: Mapped[float | None] = mapped_column(Float)
    pct_0_17: Mapped[float | None] = mapped_column(Float)
    pct_65_mas: Mapped[float | None] = mapped_column(Float)
    coef_vejez: Mapped[float | None] = mapped_column(Float)

    # Condiciones de vida, % (CondVida)
    nbi_pct: Mapped[float | None] = mapped_column(Float)
    nbi_vivienda_pct: Mapped[float | None] = mapped_column(Float)
    nbi_sanitaria_pct: Mapped[float | None] = mapped_column(Float)
    nbi_hacinamiento_pct: Mapped[float | None] = mapped_column(Float)
    nbi_escolar_pct: Mapped[float | None] = mapped_column(Float)
    nbi_subsistencia_pct: Mapped[float | None] = mapped_column(Float)
    agua_red_pct: Mapped[float | None] = mapped_column(Float)
    cloacas_pct: Mapped[float | None] = mapped_column(Float)
    gas_red_pct: Mapped[float | None] = mapped_column(Float)
    internet_pct: Mapped[float | None] = mapped_column(Float)
    propietarios_pct: Mapped[float | None] = mapped_column(Float)
    inquilinos_pct: Mapped[float | None] = mapped_column(Float)
    otra_tenencia_pct: Mapped[float | None] = mapped_column(Float)
    calidad_i_pct: Mapped[float | None] = mapped_column(Float)
    calidad_ii_pct: Mapped[float | None] = mapped_column(Float)
    calidad_iii_pct: Mapped[float | None] = mapped_column(Float)
    calidad_iv_pct: Mapped[float | None] = mapped_column(Float)

    # Condiciones de vida, hogares (PobTotalViv)
    hogares_total: Mapped[int | None] = mapped_column(Integer)
    hogares_hacinamiento: Mapped[int | None] = mapped_column(Integer)
    hogares_sanitaria: Mapped[int | None] = mapped_column(Integer)
    hogares_vivienda_inconveniente: Mapped[int | None] = mapped_column(Integer)
    hogares_calidad_iii: Mapped[int | None] = mapped_column(Integer)
    hogares_calidad_iv: Mapped[int | None] = mapped_column(Integer)
    hogares_lena_carbon: Mapped[int | None] = mapped_column(Integer)
    hogares_alquilan: Mapped[int | None] = mapped_column(Integer)

    # Educación, salud, empleo
    asistencia_10_18_pct: Mapped[float | None] = mapped_column(Float)
    secundario_completo_pct: Mapped[float | None] = mapped_column(Float)
    universitario_completo_pct: Mapped[float | None] = mapped_column(Float)
    cobertura_salud_pct: Mapped[float | None] = mapped_column(Float)
    desocupacion_pct: Mapped[float | None] = mapped_column(Float)
    actividad_principal: Mapped[str | None] = mapped_column(String(200))

    # Índice de Progreso Social
    ips_valor: Mapped[float | None] = mapped_column(Float)
    ips_nivel: Mapped[str | None] = mapped_column(String(30))
    ips_necesidades_basicas: Mapped[float | None] = mapped_column(Float)
    ips_fundamentos_bienestar: Mapped[float | None] = mapped_column(Float)
    ips_oportunidades: Mapped[float | None] = mapped_column(Float)
    ips_variacion_interanual: Mapped[float | None] = mapped_column(Float)

    # Todos los atributos originales por capa, para usos futuros sin migración.
    crudo: Mapped[dict | None] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtEstDepartamento(Base):
    """Población y superficie por departamento, más la población que vive
    fuera de los gobiernos locales (departamento − Σ gobiernos locales) —
    dato oficial que reemplaza la estimación de Gobierno. Spec §3.2."""

    __tablename__ = "ext_est_departamento"

    codigo_dpto_indec: Mapped[str] = mapped_column(String(10), primary_key=True)  # "14140"
    nombre: Mapped[str | None] = mapped_column(String(100))
    poblacion_2010: Mapped[int | None] = mapped_column(Integer)
    poblacion_2022: Mapped[int | None] = mapped_column(Integer)
    superficie_km2: Mapped[float | None] = mapped_column(Numeric(12, 2))
    poblacion_fuera_gl_2010: Mapped[int | None] = mapped_column(Integer)
    poblacion_fuera_gl_2022: Mapped[int | None] = mapped_column(Integer)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtEstPoligono(Base):
    """Polígono de cada gobierno local (WGS84, simplificado), solo para ubicar
    puntos de las otras fuentes. No se federa. Spec §3.7."""

    __tablename__ = "ext_est_poligonos"

    codigo_indec: Mapped[str] = mapped_column(String(10), primary_key=True)
    geojson: Mapped[list] = mapped_column(JSON, nullable=False)  # lista de anillos [[lng, lat], ...]
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtRenabapBarrio(Base):
    """Barrios populares del RENABAP en Córdoba. Spec §3.3."""

    __tablename__ = "ext_renabap_barrios"

    id_renabap: Mapped[str] = mapped_column(String(20), primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(200))
    familias: Mapped[int | None] = mapped_column(Integer)
    anio_creacion: Mapped[int | None] = mapped_column(Integer)
    decada_creacion: Mapped[str | None] = mapped_column(String(40))
    tipologia: Mapped[str | None] = mapped_column(String(80))
    situacion_dominial: Mapped[str | None] = mapped_column(String(80))
    energia: Mapped[str | None] = mapped_column(String(150))
    cloacas: Mapped[str | None] = mapped_column(String(150))
    agua: Mapped[str | None] = mapped_column(String(150))
    gas: Mapped[str | None] = mapped_column(String(150))
    superficie_km2: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    codigo_radio: Mapped[str | None] = mapped_column(String(20))
    codigo_indec: Mapped[str | None] = mapped_column(String(10), index=True)  # NULL: fuera de todo gobierno local
    version: Mapped[str | None] = mapped_column(String(10))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtEquipamiento(Base):
    """Establecimientos de salud y educativos (IDECOR). Spec §3.4."""

    __tablename__ = "ext_equipamientos"
    __table_args__ = (Index("ix_ext_equipamientos_tipo_codigo", "tipo", "codigo_indec"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # "salud" | "educacion"
    codigo_fuente: Mapped[str | None] = mapped_column(String(40))  # CUIE / CUE anexo
    nombre: Mapped[str | None] = mapped_column(String(250))
    categoria: Mapped[str | None] = mapped_column(String(250))
    sector: Mapped[str | None] = mapped_column(String(80))
    ambito: Mapped[str | None] = mapped_column(String(80))
    localidad_fuente: Mapped[str | None] = mapped_column(String(150))
    departamento_fuente: Mapped[str | None] = mapped_column(String(100))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    codigo_indec: Mapped[str | None] = mapped_column(String(10))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtEstadisticaVital(Base):
    """Nacimientos y defunciones por localidad y año (registro civil, IDECOR).
    Spec §3.5."""

    __tablename__ = "ext_estadisticas_vitales"

    radio_idecor: Mapped[str] = mapped_column(String(150), primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), primary_key=True)  # "nacimientos" | "defunciones"
    total: Mapped[int | None] = mapped_column(Integer)
    codigo_indec: Mapped[str | None] = mapped_column(String(10), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ExtFuentesOficialesSyncLog(Base):
    """Una fila por fuente y corrida. Append-only. Spec §3.6."""

    __tablename__ = "ext_fuentes_oficiales_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fuente: Mapped[str] = mapped_column(String(40), nullable=False)  # estadistica | renabap | idecor_equipamientos | idecor_vitales
    estado: Mapped[str] = mapped_column(String(20), nullable=False)  # ok | parcial | error
    filas_leidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_guardadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalias: Mapped[list | None] = mapped_column(JSON)
    mensaje: Mapped[str | None] = mapped_column(String(2000))
    iniciado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    finalizado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disparado_por: Mapped[str | None] = mapped_column(String(80))
