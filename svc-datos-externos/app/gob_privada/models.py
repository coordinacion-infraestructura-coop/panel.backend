"""Espejos de solo lectura de la planilla "Gobierno" de la Privada del Gobernador
(spec-datos-externos-privada-gobernador.md §2).

Misma excepción documentada que las Fases 2 y 3: sin `deleted_at`, porque cada corrida
reemplaza la tabla completa de su pestaña dentro de un SAVEPOINT; la historia queda en
`ext_gob_sync_log`. Los vínculos de la Etapa C viven en otra tabla y se apoyan en las claves
naturales (`ascasu`, `id_focom`, `id_atp`), que sobreviven al reemplazo.

Las columnas de personas (referente político, administrativo y coordinador asignados,
observaciones, responsable) no tienen lugar acá: el sync no las lee (spec §6).
"""
from datetime import date

from sqlalchemy import JSON, Boolean, Date, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.gob_transferencias.models import _Timestamps

_MONTO = Numeric(18, 2)


class ExtGobAnuncio(_Timestamps, Base):
    """Pestaña `Gobierno`: un anuncio del Gobernador por fila (spec §1.1)."""

    __tablename__ = "ext_gob_anuncio"
    __table_args__ = (UniqueConstraint("ascasu", name="uq_ext_gob_anuncio_ascasu"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ascasu: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_carga: Mapped[date | None] = mapped_column(Date)
    fecha_anuncio: Mapped[date | None] = mapped_column(Date, index=True)
    # Solo si la fecha se descartó por fuera de rango (typos como 2016 o 2027).
    fecha_anuncio_texto: Mapped[str | None] = mapped_column(String(30))
    fuente_url: Mapped[str | None] = mapped_column(Text)
    departamento: Mapped[str | None] = mapped_column(String(100))
    localidad: Mapped[str | None] = mapped_column(String(150))
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)
    ministerio: Mapped[str | None] = mapped_column(String(100))
    anuncio: Mapped[str | None] = mapped_column(Text)
    detalle: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str | None] = mapped_column(String(40))
    linea_base: Mapped[float | None] = mapped_column(Numeric(18, 4))
    valor_actual: Mapped[float | None] = mapped_column(Numeric(18, 4))
    grado_cumplimiento: Mapped[float | None] = mapped_column(Numeric(8, 4))  # 1 = 100 %
    # Texto libre del área: solo Admin y Autoridad (spec §6).
    comentarios: Mapped[str | None] = mapped_column(Text)
    # "Indicador de seguimiento Gabriel": `N-FOCOM`, `N-ATP` o un número (fila de BD Compromisos).
    indicador_seguimiento: Mapped[str | None] = mapped_column(String(40))
    estado_seguimiento: Mapped[str | None] = mapped_column(String(40))
    coinciden: Mapped[bool | None] = mapped_column(Boolean)
    # Montos en pesos que el texto del anuncio menciona; los usa el vinculador (spec §4).
    montos_mencionados: Mapped[list | None] = mapped_column(JSON)
    hash_contenido: Mapped[str] = mapped_column(String(64), nullable=False)


class ExtGobFocom(_Timestamps, Base):
    """Pestaña `FOCOM`: un convenio del Fondo Complementario de Obras por fila (spec §1.2)."""

    __tablename__ = "ext_gob_focom"
    __table_args__ = (UniqueConstraint("id_focom", "ocurrencia", name="uq_ext_gob_focom"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_focom: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # La planilla repite algún ID: la segunda aparición es `ocurrencia = 2`.
    ocurrencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expediente: Mapped[str | None] = mapped_column(String(60))
    convenio: Mapped[str | None] = mapped_column(String(60))
    fecha_convenio: Mapped[date | None] = mapped_column(Date)
    resolucion: Mapped[str | None] = mapped_column(String(60))
    departamento: Mapped[str | None] = mapped_column(String(100))
    tipo: Mapped[str | None] = mapped_column(String(40))
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)
    localidad: Mapped[str | None] = mapped_column(String(150))
    monto: Mapped[float | None] = mapped_column(_MONTO)
    concepto: Mapped[str | None] = mapped_column(Text)
    categoria: Mapped[str | None] = mapped_column(String(60))
    # PAGADO (FOCOM puro) · PAGADO ATP · PENDIENTE ATP: los dos últimos se pagaron o se pagan
    # por ATP y ya están en ATP (spec-datos-externos-tablero-gobierno.md §3.3).
    estado: Mapped[str | None] = mapped_column(String(40))
    fecha_pago: Mapped[date | None] = mapped_column(Date)
    plazo_visacion: Mapped[str | None] = mapped_column(String(60))
    anio: Mapped[int | None] = mapped_column(Integer, index=True)
    estado_obra: Mapped[str | None] = mapped_column(String(40))


class ExtGobAtpHistorico(_Timestamps, Base):
    """Pestaña `ATP` (IMPORTRANGE de la planilla semanal): solo transferencias anteriores a
    2026. 2026 sigue saliendo de ATP Interno (svc-gralgob), así nada se cuenta dos veces
    (spec §3.3)."""

    __tablename__ = "ext_gob_atp_historico"
    __table_args__ = (UniqueConstraint("id_atp", "ocurrencia", name="uq_ext_gob_atp_historico"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_atp: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    ocurrencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    departamento: Mapped[str | None] = mapped_column(String(100))
    localidad: Mapped[str | None] = mapped_column(String(150))
    codigo_indec: Mapped[str | None] = mapped_column(String(20), index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    anio: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    monto: Mapped[float] = mapped_column(_MONTO, nullable=False)
