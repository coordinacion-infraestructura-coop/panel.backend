"""Espejos de solo lectura de las planillas de transferencias de Gobierno
(spec-datos-externos-fase2-transferencias.md §2).

Excepción documentada a la regla de borrado lógico: no tienen `deleted_at`. Cada corrida
reemplaza la tabla completa de su fuente (§3); la historia queda en `ext_gob_sync_log`.

`codigo_indec` sin FK al nomenclador: una fila con un código que el nomenclador todavía no
tiene se guarda igual y se informa como anomalía.
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Restringidos (spec §6): solo Admin/Autoridad, nunca en logs ni en `anomalias`.
CAMPOS_RESTRINGIDOS_EMPLEADOS = ("empleados", "salario_promedio", "masa_salarial")


def _now() -> datetime:
    return datetime.now(timezone.utc)


_MONTO = Numeric(18, 2)


class _Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class ExtGobCopa(_Timestamps, Base):
    """Planilla "11.1 COPARTICIPACION", pestaña `COPA`: una fila por localidad y quincena."""

    __tablename__ = "ext_gob_copa"
    __table_args__ = (UniqueConstraint("codigo_indec", "anio", "mes", "quincena", name="uq_ext_gob_copa"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    quincena: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_pago: Mapped[date | None] = mapped_column(Date)
    id_copa: Mapped[int | None] = mapped_column(Integer)
    indice: Mapped[float | None] = mapped_column(Numeric(14, 10))
    bruto: Mapped[float | None] = mapped_column(_MONTO)
    ajuste: Mapped[float | None] = mapped_column(_MONTO)
    total_ajustado: Mapped[float | None] = mapped_column(_MONTO)
    neto_resultante: Mapped[float | None] = mapped_column(_MONTO)
    neto_a_transferir: Mapped[float | None] = mapped_column(_MONTO)
    caja_jubilaciones: Mapped[float | None] = mapped_column(_MONTO)
    apross: Mapped[float | None] = mapped_column(_MONTO)
    # {encabezado de la planilla: monto}; todas las columnas de descuento, Caja y APROSS incluidas.
    descuentos: Mapped[dict | None] = mapped_column(JSON)


class ExtGobFofindes(_Timestamps, Base):
    """Planilla "11.1 FOFINDES": una fila por localidad y pago. Un mes puede tener dos pagos
    (diciembre de 2024), por eso la fecha de pago entra en la clave."""

    __tablename__ = "ext_gob_fofindes"
    __table_args__ = (
        UniqueConstraint("codigo_indec", "anio", "mes", "fecha_pago", name="uq_ext_gob_fofindes"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_pago: Mapped[date | None] = mapped_column(Date)
    total_parte_variable: Mapped[float | None] = mapped_column(_MONTO)
    excedente_30: Mapped[float | None] = mapped_column(_MONTO)
    excedente_70: Mapped[float | None] = mapped_column(_MONTO)
    bruto: Mapped[float | None] = mapped_column(_MONTO)
    descuentos: Mapped[dict | None] = mapped_column(JSON)
    neto_resultante: Mapped[float | None] = mapped_column(_MONTO)
    neto_a_transferir: Mapped[float | None] = mapped_column(_MONTO)


class ExtGobFodemep(_Timestamps, Base):
    """Planilla "11.1 FODEMEP", pestaña `FODEMEP`: una fila por localidad y mes."""

    __tablename__ = "ext_gob_fodemep"
    __table_args__ = (UniqueConstraint("codigo_indec", "periodo", name="uq_ext_gob_fodemep"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    periodo: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # primer día del mes
    fecha_pago: Mapped[date | None] = mapped_column(Date)
    presupuestado: Mapped[float | None] = mapped_column(_MONTO)  # `Total FODEEMEP`
    acumulado: Mapped[float | None] = mapped_column(_MONTO)  # retenido, a confirmar con el área (spec §8.1)
    neto_a_transferir: Mapped[float | None] = mapped_column(_MONTO)


class ExtGobFodemepEstado(_Timestamps, Base):
    """Planilla "11.1 FODEMEP", pestaña `ESTADO`: estado de adhesión por localidad."""

    __tablename__ = "ext_gob_fodemep_estado"

    codigo_indec: Mapped[str] = mapped_column(String(20), primary_key=True)
    estado: Mapped[str | None] = mapped_column(String(30))  # NORMAL | SUSPENDIDO | CORTADO | NO ADHERIDO
    saldo_gestion: Mapped[float | None] = mapped_column(_MONTO)


class ExtGobFommep(_Timestamps, Base):
    """Planilla "11.1 FOMMEP", pestaña `FROMMEP`: una fila por localidad y año."""

    __tablename__ = "ext_gob_fommep"
    __table_args__ = (UniqueConstraint("codigo_indec", "anio", name="uq_ext_gob_fommep"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    cant_moviles: Mapped[int | None] = mapped_column(Integer)
    monto_moviles: Mapped[float | None] = mapped_column(_MONTO)
    cant_edificios_a: Mapped[int | None] = mapped_column(Integer)
    monto_edificios_a: Mapped[float | None] = mapped_column(_MONTO)
    cant_edificios_b: Mapped[int | None] = mapped_column(Integer)
    monto_edificios_b: Mapped[float | None] = mapped_column(_MONTO)
    cant_edificios_c: Mapped[int | None] = mapped_column(Integer)
    monto_edificios_c: Mapped[float | None] = mapped_column(_MONTO)
    cant_edificios_total: Mapped[int | None] = mapped_column(Integer)
    monto_edificios_total: Mapped[float | None] = mapped_column(_MONTO)
    monto_total: Mapped[float | None] = mapped_column(_MONTO)


class ExtGobEmpleados(_Timestamps, Base):
    """Planilla "13. EMPLEADOS", pestaña `Activos MyC`: una fila por localidad y año.
    Todo restringido (CAMPOS_RESTRINGIDOS_EMPLEADOS)."""

    __tablename__ = "ext_gob_empleados"
    __table_args__ = (UniqueConstraint("codigo_indec", "anio", name="uq_ext_gob_empleados"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo_indec: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    empleados: Mapped[int | None] = mapped_column(Integer)
    salario_promedio: Mapped[float | None] = mapped_column(_MONTO)
    masa_salarial: Mapped[float | None] = mapped_column(_MONTO)
