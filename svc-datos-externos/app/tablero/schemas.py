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
    caja: list[float | None]  # del mes ("mes de X de cada año")
    apross: list[float | None]
    acumulado_caja: list[float | None]  # de enero a ese mes ("acumulado a X de cada año")
    acumulado_apross: list[float | None]


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
    anio: int
    codigo_indec: str
    localidad: str
    departamento: str
    cant_moviles: int
    monto_moviles: float
    cant_edificios: int
    monto_edificios: float
    monto_total: float


class FommepAnio(BaseModel):
    anio: int
    kpis: FommepKpis


class FommepResponse(BaseModel):
    """FOMMEP tiene años propios (spec-tablero-gobierno-panel.md §2.5 #6): la respuesta trae cada
    año y la gestión completa, y la pantalla elige sin volver a pedir."""
    concepto: str = "fommep"
    anios: list[int]
    gestion: FommepKpis | None
    por_anio: list[FommepAnio]
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
    fondo_ambiental: float = 0.0  # Fase 3: pagado a localidades (sin comunidades regionales)
    total: float
    por_habitante: float | None


class ResumenResponse(BaseModel):
    concepto: str = "resumen"
    anio: int
    periodo_hasta: date | None  # último mes con COPA en el año
    total: ResumenFila
    por_departamento: list[ResumenFila]
    por_localidad: list[ResumenFila]


# ── Etapa 3: fondos (spec-datos-externos-fase3-fondos.md §4) ──────────────────────────
# Mismo criterio que FOMMEP: cada respuesta trae todos los años y la gestión completa, y la
# pantalla elige el año sin volver a pedir.


class EstadoMonto(BaseModel):
    estado: str
    cantidad: int
    monto: float


class PrestamosKpis(BaseModel):
    monto: float
    prestamos: int
    localidades: int


class FpermPrestamo(BaseModel):
    anio: int | None  # año de la fecha; nulo = listo para pagar
    codigo_indec: str | None
    localidad: str | None
    departamento: str | None
    etapas: str | None
    fecha: date | None
    monto_total: float
    cuota: float | None
    plazo: int | None
    mes_inicio_descuento: int | None
    destino: str | None
    ord_res: str | None


class FpermLocalidad(BaseModel):
    codigo_indec: str
    localidad: str
    departamento: str
    ultima_etapa: int | None
    recibio_ultima: bool
    recibio_anteultima: bool
    etapas_disponibles: list[int]
    disponible: float


class FpermAnio(BaseModel):
    anio: int
    otorgado: PrestamosKpis
    mensual: list[float | None]


class FondoPermanenteResponse(BaseModel):
    concepto: str = "fondo-permanente"
    # Foto de hoy, no depende del año.
    ultima_etapa_habilitada: int | None
    saldo_cuenta: float | None  # nulo con filtro territorial: es del fondo entero
    localidades_adheridas: int
    recibieron_ultima: int
    recibieron_anteultima: int
    disponible: float
    localidades_con_disponible: int
    listo_para_pagar: PrestamosKpis
    # Préstamos otorgados.
    anios: list[int]
    gestion: PrestamosKpis
    por_anio: list[FpermAnio]
    prestamos: list[FpermPrestamo]
    localidades: list[FpermLocalidad]


class FondoAmbientalKpis(BaseModel):
    localidades: int
    entes: int
    convenios: int
    afectado: float
    pagado: float
    ingresos: float | None  # nulo con filtro territorial: el ingreso es del fondo entero
    disponible: float | None
    estados: list[EstadoMonto]


class FondoAmbientalAnio(BaseModel):
    anio: int
    kpis: FondoAmbientalKpis


class FondoAmbientalFila(BaseModel):
    anio: int | None
    codigo: str
    es_ente: bool
    localidad: str
    departamento: str | None
    expediente: str | None
    convenio: str | None
    fecha_convenio: date | None
    resolucion: str | None
    objeto: str | None
    monto: float
    estado: str | None
    fecha_estado: date | None


class ObjetoMonto(BaseModel):
    objeto: str
    cantidad: int
    monto: float


class FondoAmbientalResponse(BaseModel):
    concepto: str = "fondo-ambiental"
    anios: list[int]
    gestion: FondoAmbientalKpis | None
    por_anio: list[FondoAmbientalAnio]
    objetos: list[ObjetoMonto]  # de la gestión; la pantalla recalcula por año desde las filas
    convenios: list[FondoAmbientalFila]


class CregTipo(BaseModel):
    credito: float | None  # nulo con filtro territorial
    cuotas: int  # sin anuladas
    monto_cuotas: float
    pagado: float
    a_pagar: float
    saldo: float | None


class CregKpis(BaseModel):
    funcionamiento: CregTipo
    obras: CregTipo
    total: CregTipo
    comunidades: int
    estados: list[EstadoMonto]


class CregAnio(BaseModel):
    anio: int
    kpis: CregKpis


class CregCuota(BaseModel):
    anio: int | None
    codigo_ente: str
    comunidad: str
    departamento: str | None
    tipo: str | None
    expediente: str | None
    destino: str | None
    monto: float | None
    cuota: int | None
    monto_cuota: float | None
    estado: str | None
    fecha_pago: date | None
    fecha_rendicion: date | None


class ComunidadesRegionalesResponse(BaseModel):
    concepto: str = "comunidades-regionales"
    departamentos: list[str] | None  # filtro aplicado; nulo = toda la provincia
    anios: list[int]
    gestion: CregKpis | None
    por_anio: list[CregAnio]
    cuotas: list[CregCuota]
