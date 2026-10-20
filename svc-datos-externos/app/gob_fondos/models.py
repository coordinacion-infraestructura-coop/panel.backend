"""Espejos de solo lectura de las planillas de fondos de Gobierno
(spec-datos-externos-fase3-fondos.md §2).

Misma excepción documentada que la Fase 2: sin `deleted_at`, porque cada corrida reemplaza la
tabla completa de su fuente; la historia queda en `ext_gob_sync_log`. Códigos sin FK al
nomenclador.

Las columnas de personas de estas planillas (`INTENDENTE`, `CUIT`, `OBSERVACIONES`) no tienen
lugar acá: el sync ni siquiera las lee (spec §3).
"""
from datetime import date

from sqlalchemy import Boolean, Date, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.gob_transferencias.models import _Timestamps

_MONTO = Numeric(18, 2)


class ExtGobFpermLocalidad(_Timestamps, Base):
    """"7. FONDO PERMANENTE", pestaña `FONDO PERM`: una fila por localidad adherida."""

    __tablename__ = "ext_gob_fperm_localidad"

    codigo_indec: Mapped[str] = mapped_column(String(20), primary_key=True)
    ultima_etapa: Mapped[int | None] = mapped_column(Integer)  # última etapa recibida
    disponible: Mapped[float | None] = mapped_column(_MONTO)  # suma de sus etapas sin otorgar
    recibio_ultima: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recibio_anteultima: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ExtGobFpermEtapa(_Timestamps, Base):
    """`FONDO PERM CUOTAS`: etapas disponibles sin otorgar, una fila por localidad y etapa."""

    __tablename__ = "ext_gob_fperm_etapa"
    __table_args__ = (UniqueConstraint("codigo_indec", "etapa", name="uq_ext_gob_fperm_etapa"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    etapa: Mapped[int] = mapped_column(Integer, nullable=False)
    monto: Mapped[float | None] = mapped_column(_MONTO)


class ExtGobFpermPrestamo(_Timestamps, Base):
    """`IMPORT_Listo`: préstamos. Sin fecha = listo para pagar; con fecha = otorgado."""

    __tablename__ = "ext_gob_fperm_prestamo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)
    etapas_texto: Mapped[str | None] = mapped_column(String(60))
    etapa_desde: Mapped[int | None] = mapped_column(Integer)
    etapa_hasta: Mapped[int | None] = mapped_column(Integer)
    fecha: Mapped[date | None] = mapped_column(Date)
    mes_inicio_descuento: Mapped[int | None] = mapped_column(Integer)
    monto_total: Mapped[float | None] = mapped_column(_MONTO)
    cuota: Mapped[float | None] = mapped_column(_MONTO)
    plazo: Mapped[int | None] = mapped_column(Integer)
    ord_res: Mapped[str | None] = mapped_column(String(60))
    sticker: Mapped[str | None] = mapped_column(String(120))
    fecha_ingreso: Mapped[date | None] = mapped_column(Date)
    destino: Mapped[str | None] = mapped_column(Text)


class ExtGobFondoAmbiental(_Timestamps, Base):
    """"9. FONDO AMBIENTAL", pestaña `Fondo`: un convenio por fila, con una localidad o una
    comunidad regional (ente)."""

    __tablename__ = "ext_gob_fondo_ambiental"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)
    codigo_ente: Mapped[str | None] = mapped_column(String(20))
    # Solo entes: nombre y departamento como vienen en la planilla. El código `500` agrupa entes
    # intermunicipales que no son comunidades regionales y no están en el nomenclador.
    nombre_ente: Mapped[str | None] = mapped_column(String(150))
    departamento_ente: Mapped[str | None] = mapped_column(String(100))
    anio: Mapped[int | None] = mapped_column(Integer, index=True)
    expediente: Mapped[str | None] = mapped_column(String(60))
    convenio: Mapped[str | None] = mapped_column(String(60))
    fecha_convenio: Mapped[date | None] = mapped_column(Date)
    resolucion: Mapped[str | None] = mapped_column(String(60))
    fecha_resolucion: Mapped[date | None] = mapped_column(Date)
    objeto: Mapped[str | None] = mapped_column(Text)
    monto: Mapped[float | None] = mapped_column(_MONTO)
    estado: Mapped[str | None] = mapped_column(String(40))
    fecha_estado: Mapped[date | None] = mapped_column(Date)


class ExtGobCregCuota(_Timestamps, Base):
    """"17. Comunidades Regionales", pestaña `Fondo`: una cuota por fila."""

    __tablename__ = "ext_gob_creg_cuota"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_ente: Mapped[str | None] = mapped_column(String(20), index=True)
    tipo: Mapped[str | None] = mapped_column(String(30))  # Funcionamiento | Obras
    anio: Mapped[int | None] = mapped_column(Integer, index=True)
    expediente: Mapped[str | None] = mapped_column(String(60))
    destino: Mapped[str | None] = mapped_column(Text)  # nulo si en la planilla vino como fecha
    monto: Mapped[float | None] = mapped_column(_MONTO)
    cuota: Mapped[int | None] = mapped_column(Integer)
    monto_cuota: Mapped[float | None] = mapped_column(_MONTO)
    estado: Mapped[str | None] = mapped_column(String(40))
    fecha_pago: Mapped[date | None] = mapped_column(Date)
    resolucion: Mapped[str | None] = mapped_column(String(60))
    fecha_rendicion: Mapped[date | None] = mapped_column(Date)


class ExtGobFondoValor(_Timestamps, Base):
    """Valores sueltos de las planillas de fondos: saldo en cuenta y última etapa habilitada
    (Fondo Permanente), ingresos por año (Fondo Ambiental), crédito de funcionamiento y de obras
    por año (Comunidades Regionales). Cada fuente reemplaza solo sus filas (`fondo`)."""

    __tablename__ = "ext_gob_fondo_valor"
    __table_args__ = (UniqueConstraint("fondo", "concepto", "anio", name="uq_ext_gob_fondo_valor"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fondo: Mapped[str] = mapped_column(String(40), nullable=False)
    concepto: Mapped[str] = mapped_column(String(40), nullable=False)
    anio: Mapped[int | None] = mapped_column(Integer)
    monto: Mapped[float | None] = mapped_column(_MONTO)
