from datetime import date, datetime

from pydantic import BaseModel


class LocalidadFiltro(BaseModel):
    id_geo: str | None
    codigo_indec: str
    nombre: str
    departamento: str
    tipo: str | None  # "Municipio" | "Comuna"


class FuenteFrescura(BaseModel):
    fuente: str
    etiqueta: str
    estado: str  # "ok" | "parcial" | "fallido" | "sin_datos"
    ultima_corrida: datetime | None
    ultimo_periodo: date | None = None
    detalle: str | None = None


class TableroMetaResponse(BaseModel):
    localidades: list[LocalidadFiltro]
    anios: list[int]
    frescura: list[FuenteFrescura]


class InicioKpis(BaseModel):
    localidades: int
    municipios: int
    comunas: int
    poblacion: int
    transferido: float
    por_habitante: float | None


class InicioDepartamento(BaseModel):
    departamento: str
    localidades: int
    poblacion: int
    transferido: float
    por_habitante: float | None


class InicioResponse(BaseModel):
    anio: int
    periodo_hasta: date | None  # último mes con transferencias publicadas en el año
    kpis: InicioKpis
    por_departamento: list[InicioDepartamento]


class ConceptoMonto(BaseModel):
    concepto: str
    etiqueta: str
    monto: float


class Pago(BaseModel):
    """Un pago (quincena de COPA o pago de FOFINDES) o un mes, sumado sobre el filtro."""
    anio: int
    mes: int  # 1-12
    quincena: int | None = None
    fecha_pago: date | None
    bruto: float
    neto: float


class Retencion(BaseModel):
    anio: int
    caja: float | None  # Caja de Jubilaciones / COPA bruta
    apross: float | None  # APROSS / COPA bruta


class RetencionMensual(BaseModel):
    anio: int
    caja: list[float | None]
    apross: list[float | None]


class Retenciones(BaseModel):
    mes_referencia: int | None  # 1-12: mes del "acumulado a" y del "mismo mes de cada año"
    mensual: list[RetencionMensual]
    acumulado: list[Retencion]
    mismo_mes: list[Retencion]


class PctSueldos(BaseModel):
    """Masa salarial ÷ (COPA + FOFINDES) del último mes completo (spec Fase 2 §5.1). Solo
    porcentajes: la masa salarial no viaja."""
    bruto: float | None
    neto: float | None
    anio_masa: int | None  # None: ninguna localidad del filtro tiene masa salarial
    mes_referencia: date
    localidades_con_dato: int
    localidades: int
    incluye_fofindes: bool


class TransferenciasResponse(BaseModel):
    concepto: str
    etiqueta: str
    anio: int
    ultimo_periodo: date | None
    total_anio: float
    acumulado_anterior: float | None  # año anterior, de enero al mismo mes
    variacion: float | None
    ultimo_mes: float | None
    mensual: list[float | None]
    mensual_anterior: list[float | None]
    por_concepto: list[ConceptoMonto]  # siempre de Transparencia
    localidades: int
    # Etapa 2: desde la planilla de Gobierno cuando tiene el año (spec Fase 2 §5)
    fuente: str = "transparencia"  # "planilla" | "transparencia"
    fuente_anterior: str = "transparencia"
    total_neto_anio: float | None = None
    mensual_neto: list[float | None] | None = None
    ultimo_pago: Pago | None = None
    ultimo_mes_completo: Pago | None = None
    pagos: list[Pago] = []
    descuentos: list[ConceptoMonto] = []
    retenciones: Retenciones | None = None
    pct_sueldos: PctSueldos | None = None


class EstadoCantidad(BaseModel):
    estado: str
    cantidad: int


class FodemeepKpis(BaseModel):
    localidades: int
    presupuestado_gestion: float
    transferido_gestion: float
    ultimo_periodo: date | None
    presupuestado_ultimo: float | None
    transferido_ultimo: float | None
    retenido_ultimo: float | None


class FodemeepLocalidad(BaseModel):
    codigo_indec: str
    localidad: str
    departamento: str
    estado: str | None
    meses: list[float | None]
    total: float


class FodemeepResponse(BaseModel):
    concepto: str = "fodemeep"
    anio: int
    kpis: FodemeepKpis
    mensual_transferido: list[float | None]
    mensual_retenido: list[float | None]
    mensual_presupuestado: list[float | None]
    por_localidad: list[FodemeepLocalidad]
    estados: list[EstadoCantidad]


class Grupo(BaseModel):
    cantidad: int
    monto: float


class FommepKpis(BaseModel):
    localidades: int
    monto_total: float
    moviles: Grupo
    edificios_a: Grupo
    edificios_b: Grupo
    edificios_c: Grupo
    edificios: Grupo
    otros: float  # monto_total − móviles − edificios (spec Fase 2 §8.2)


class FommepLocalidad(BaseModel):
    codigo_indec: str
    localidad: str
    departamento: str
    cant_moviles: int
    monto_moviles: float
    cant_edificios: int
    monto_edificios: float
    monto_total: float


class FommepResponse(BaseModel):
    concepto: str = "fommep"
    anio: int  # el año efectivamente mostrado (FOMMEP tiene años propios)
    anios: list[int]
    kpis: FommepKpis | None
    por_localidad: list[FommepLocalidad]


class ResumenFila(BaseModel):
    clave: str  # departamento o código INDEC
    localidad: str | None = None
    departamento: str
    tipo: str | None = None
    localidades: int
    poblacion: int
    copa: float
    fofindes: float
    total: float
    por_habitante: float | None


class ResumenResponse(BaseModel):
    concepto: str = "resumen"
    anio: int
    periodo_hasta: date | None  # último mes con COPA en el año
    total: ResumenFila
    por_departamento: list[ResumenFila]
    por_localidad: list[ResumenFila]
