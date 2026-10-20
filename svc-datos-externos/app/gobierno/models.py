import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Campos de `ExtGobLocalidad` que sólo pueden ver los roles `Admin` y `Autoridad`
# (spec-datos-externos-fase1-nomenclador-demografia.md §3.2 y §7). Viajan
# juntos en el objeto `ficha_gobierno` del rollup; nunca van a logs ni a
# `anomalias`.
CAMPOS_RESTRINGIDOS = (
    "electores",
    "empleados",
    "masa_salarial",
    "intendente",
    "reelecto",
    "partido",
    "continuidad",
    "legislador",
    "partido_legislador",
    "contacto_intendente",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ExtGobLocalidad(Base):
    """Puente código INDEC de gobierno local ↔ padrón oficial (`id_geo`), más
    la ficha de localidad que mantiene Gobierno. Sólo los 427 gobiernos
    locales; comunidades regionales y zonas rurales van a `ExtGobEnte`.

    El código INDEC es una llave alternativa: el padrón oficial sigue siendo
    `viv_geo_localidades` (ADR-024/026). `id_geo` sin FK real (cross-DB).
    """

    __tablename__ = "ext_gob_localidades"

    codigo_indec: Mapped[str] = mapped_column(String(20), primary_key=True)
    nombre_gob: Mapped[str] = mapped_column(String(150), nullable=False)
    departamento_gob: Mapped[str] = mapped_column(String(100), nullable=False)
    codigo_dpto_indec: Mapped[str | None] = mapped_column(String(10))
    id_copa: Mapped[int | None] = mapped_column(Integer, unique=True)
    tipo: Mapped[str | None] = mapped_column(String(2))  # "MU" | "CO"
    id_geo: Mapped[str | None] = mapped_column(String(20), index=True)
    match_tipo: Mapped[str | None] = mapped_column(String(20))

    # Públicos
    superficie_km2: Mapped[float | None] = mapped_column(Numeric(12, 4))  # radio municipal (IDECOR)
    poblacion_2010: Mapped[int | None] = mapped_column(Integer)
    # Sólo control: la población que se muestra es la del Censo (ext_geo_censo).
    poblacion_2022_gob: Mapped[int | None] = mapped_column(Integer)
    # Sólo control, nunca se exponen: totales de la Vista en millones de pesos, contra los que
    # se concilia lo calculado desde las planillas base (spec-datos-externos-fase2-transferencias.md §4.2).
    copa_vista_m: Mapped[float | None] = mapped_column(Numeric(18, 4))
    fofindes_vista_m: Mapped[float | None] = mapped_column(Numeric(18, 4))

    # Restringidos (ver CAMPOS_RESTRINGIDOS)
    electores: Mapped[int | None] = mapped_column(Integer)
    empleados: Mapped[int | None] = mapped_column(Integer)
    masa_salarial: Mapped[float | None] = mapped_column(Numeric(18, 2))
    intendente: Mapped[str | None] = mapped_column(String(150))
    reelecto: Mapped[bool | None] = mapped_column(Boolean)
    partido: Mapped[str | None] = mapped_column(String(150))
    continuidad: Mapped[bool | None] = mapped_column(Boolean)
    legislador: Mapped[str | None] = mapped_column(String(150))
    partido_legislador: Mapped[str | None] = mapped_column(String(150))
    contacto_intendente: Mapped[str | None] = mapped_column(String(40))  # dato personal

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtGobEnte(Base):
    """Códigos que usan las planillas de Gobierno y NO son localidades:
    comunidades regionales (`428`–`453`) y zonas rurales (`nnZR`)."""

    __tablename__ = "ext_gob_entes"

    codigo: Mapped[str] = mapped_column(String(20), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo_ente: Mapped[str] = mapped_column(String(20), nullable=False)  # "comunidad_regional" | "zona_rural"
    departamento: Mapped[str | None] = mapped_column(String(100))
    # Sólo zona_rural. Es una estimación del área: el Censo 2022 no desagrega
    # por departamento la población sin gobierno local.
    poblacion_2022: Mapped[int | None] = mapped_column(Integer)
    poblacion_2010: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtGobSyncLog(Base):
    """Una fila por corrida y fuente. Append-only, mismo criterio que
    `ext_transferencias_sync_log`. Genérico (columna `fuente`) para que las
    fases siguientes no creen un log por planilla.

    `anomalias` nunca incluye valores de campos restringidos: sólo el código
    de la localidad y el nombre del campo."""

    __tablename__ = "ext_gob_sync_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fuente: Mapped[str] = mapped_column(String(40), nullable=False)  # "nomenclador" | "resumen_vista" (hasta v1.1.0 del spec: "datos_loc")
    filas_leidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_upsert: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filas_sin_match: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalias: Mapped[dict | list | None] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)  # "ok" | "parcial" | "fallido"
    corrida_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    disparado_por: Mapped[str | None] = mapped_column(String(80))
