"""Gestiones (demandas) de la Secretaría Privada del Ministro.

Migrado desde BigQuery `infra_gestion.gestiones` / `gestiones_eventos`.
Patrón panel-module (ADR-009): estado como VARCHAR + CHECK (sin ENUM, sin máquina de
transiciones). Concurrencia por lock optimista sobre `updated_at`.

Las columnas legacy `categoria_general_id`, `subcategoria_id`, `tipo_demanda_principal_id`,
`tipo_gestion`, `canal_origen` se migran verbatim (§3.11 del spec). Las columnas de mejora
(`categoria_id`, `programa_id`, `area_id`, `ok_gobernador`, `ok_ministro`,
`acciones_implementadas`) las agregan migraciones posteriores de los specs hijos.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, JSON, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

OK_VALUES = ("SI", "NO", "PENDIENTE")
_OK_SQL = ", ".join(f"'{v}'" for v in OK_VALUES)

from app.database import Base

# Estados posibles (los 6 del sistema viejo, strings literales — "INNAUGURAR" con doble N
# es load-bearing). Sin validación de transición (ADR-009).
ESTADOS = (
    "INGRESADO",
    "DERIVADO A SUAC",
    "LISTA PARA INNAUGURAR",
    "FINALIZADA",
    "NO REMITE SUAC",
    "ARCHIVADO",
)
URGENCIAS = ("Alta", "Media", "Baja")

_ESTADOS_SQL = ", ".join(f"'{e}'" for e in ESTADOS)
_URGENCIAS_SQL = ", ".join(f"'{u}'" for u in URGENCIAS)


class Gestion(Base):
    __tablename__ = "priv_gestiones"
    __table_args__ = (
        CheckConstraint(f"estado IN ({_ESTADOS_SQL})", name="ck_priv_gestiones_estado"),
        CheckConstraint(f"urgencia IN ({_URGENCIAS_SQL})", name="ck_priv_gestiones_urgencia"),
        CheckConstraint(f"ok_gobernador IN ({_OK_SQL})", name="ck_priv_gestiones_ok_gob"),
        CheckConstraint(f"ok_ministro IN ({_OK_SQL})", name="ck_priv_gestiones_ok_min"),
    )

    # BQ es STRING sin límite en todas estas columnas — la muestra chica del Anexo D no
    # reflejaba la diversidad real (datos cargados desde 2004). El primer --truncate contra
    # datos reales rompió con "value too long for character varying(30)" en origen/geo_id.
    # Anchos generosos acá; son "código" pero no enums reales — sin CHECK salvo estado/urgencia.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    id_legacy: Mapped[str | None] = mapped_column(String(100), unique=True)

    nro_expediente: Mapped[str | None] = mapped_column(String(120))
    origen: Mapped[str | None] = mapped_column(String(100))

    estado: Mapped[str] = mapped_column(String(60), nullable=False, server_default="INGRESADO")
    fecha_ingreso: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_estado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_finalizacion: Mapped[date | None] = mapped_column(Date)

    urgencia: Mapped[str | None] = mapped_column(String(30), server_default="Media")

    ministerio_agencia_id: Mapped[str | None] = mapped_column(
        String(120), ForeignKey("priv_cat_ministerio_agencia.id", name="fk_priv_gestion_ministerio")
    )
    organismo_id: Mapped[str | None] = mapped_column(String(300))
    derivado_a_id: Mapped[str | None] = mapped_column(String(300))
    categoria_general_id: Mapped[str | None] = mapped_column(
        String(120), ForeignKey("priv_cat_categoria_general.id", name="fk_priv_gestion_categoria")
    )
    subcategoria_id: Mapped[str | None] = mapped_column(String(120))
    tipo_demanda_principal_id: Mapped[str | None] = mapped_column(String(120))
    subtipo_detalle: Mapped[str | None] = mapped_column(Text)

    detalle: Mapped[str] = mapped_column(Text, nullable=False)
    observaciones: Mapped[str | None] = mapped_column(Text)

    geo_id: Mapped[str | None] = mapped_column(String(60))
    departamento: Mapped[str] = mapped_column(String(120), nullable=False)
    localidad: Mapped[str] = mapped_column(String(200), nullable=False)
    direccion: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Numeric(12, 7))
    lon: Mapped[float | None] = mapped_column(Numeric(12, 7))

    # BQ NUMERIC sin escala fija; hay al menos un valor sucio muy grande en el origen
    # (SUM(costo_estimado) ~ 7.2e13). Numeric(18,2) da margen.
    costo_estimado: Mapped[float | None] = mapped_column(Numeric(18, 2))
    costo_moneda: Mapped[str | None] = mapped_column(String(20))

    tipo_gestion: Mapped[str | None] = mapped_column(String(120))
    canal_origen: Mapped[str | None] = mapped_column(String(120))

    # Mejora E1/E2 (migración 0002) — catálogos editables + campos nuevos.
    categoria_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("priv_categorias.id"))
    programa_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("priv_programas.id"))
    area_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("priv_areas.id"))
    ok_gobernador: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDIENTE")
    ok_ministro: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDIENTE")
    acciones_implementadas: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[str | None] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GestionEvento(Base):
    """Log append-only de cambios (estado y campo a campo). Migrado 1:1 desde
    `gestiones_eventos`. La traza de derivaciones histórica vive dentro de `metadata_json`;
    `spec-privada-flujo-derivaciones.md` (ADR-013) la estructura aparte."""

    __tablename__ = "priv_gestiones_eventos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    gestion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("priv_gestiones.id", name="fk_priv_evento_gestion"), nullable=False
    )
    fecha_evento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    usuario: Mapped[str] = mapped_column(String(200), nullable=False)  # REQUIRED en el origen
    rol_usuario: Mapped[str | None] = mapped_column(String(40))
    tipo_evento: Mapped[str] = mapped_column(String(60), nullable=False)
    estado_anterior: Mapped[str | None] = mapped_column(String(60))
    estado_nuevo: Mapped[str | None] = mapped_column(String(60))
    campo_modificado: Mapped[str | None] = mapped_column(String(100))
    valor_anterior: Mapped[str | None] = mapped_column(Text)
    valor_nuevo: Mapped[str | None] = mapped_column(Text)
    comentario: Mapped[str | None] = mapped_column(Text)
    # JSON por compatibilidad con SQLite en tests; el backfill del DAG (spec-privada-flujo-
    # derivaciones.md / ADR-013) puede migrarlo a JSONB si necesita operadores de PostgreSQL.
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
