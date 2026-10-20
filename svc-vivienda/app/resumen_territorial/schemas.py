from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ResumenComunicacion(BaseModel):
    fecha: date
    texto: str | None = None
    area: str | None = None
    autor: str | None = None


class ResumenSubestados(BaseModel):
    juridico: str | None = None
    tecnico: str | None = None
    financiero: str | None = None


class PrivadaConteos(BaseModel):
    por_estado: dict[str, int]
    total: int


class ResumenPrograma(BaseModel):
    """Una línea de programa (Vivienda) o de gestión roll-up (Privada) dentro de una localidad."""

    area: str                              # "vivienda" | "privada"  (clave del filtro de visibilidad)
    programa: str                          # vivienda: cordon_cuneta|cordoba_hogar|mi_lugar · privada: "gestiones"
    programa_label: str
    entidad_id: str | None = None          # id CC/CH/ML · None en la línea roll-up de Privada
    detalle: str | None = None             # ML: nombre del proyecto · Privada: breakdown corto de gestiones
    estado_general_id: int | None = None
    estado_general_label: str | None = None
    estado_general_bg: str | None = None
    estado_general_text_color: str | None = None
    subestados: ResumenSubestados | None = None
    checklist_total: int = 0
    checklist_faltan: int = 0
    checklist_iniciado: bool = False
    checklist_faltantes: list[str] = Field(default_factory=list)
    ultima_comunicacion: ResumenComunicacion | None = None
    monto: float | None = None
    # ATP (gralgob): monto efectivamente pagado a la fecha, como lo trae
    # `rollup_territorial` de svc-gralgob (`entregado_sum`) — ya se calculaba
    # para clasificar `estado_general_label` (Pendiente/Parcial/Pagado) pero
    # se descartaba sin llegar al payload (ADR-025, 2026-10-01). None para
    # cualquier otro `programa` que no sea "atp".
    monto_entregado: float | None = None
    expediente: str | None = None
    privada_conteos: PrivadaConteos | None = None


class FichaGobierno(BaseModel):
    """Datos institucionales de la localidad que mantiene la Secretaría General
    de Gobierno (planilla `DATOS LOC`, vía svc-datos-externos). **Restringido:
    sólo lo reciben los roles `Admin` y `Autoridad`** —
    `service.filtrar_por_visibilidad` lo reemplaza por `None` para cualquier otro rol
    (spec-datos-externos-fase1-nomenclador-demografia.md §7)."""

    electores: int | None = None
    empleados: int | None = None
    masa_salarial: float | None = None
    intendente: str | None = None
    reelecto: bool | None = None
    partido: str | None = None
    continuidad: bool | None = None
    legislador: str | None = None
    partido_legislador: str | None = None
    contacto_intendente: str | None = None          # dato personal


class ZonaRural(BaseModel):
    """Población sin gobierno local de un departamento; no se suma a ninguna
    localidad. `fuente = "censo"`: dato oficial (departamento − Σ gobiernos
    locales, Estadística Córdoba); `"gobierno_estimacion"`: estimación del
    área de Gobierno (spec-datos-externos-fuentes-oficiales.md §6)."""

    departamento: str
    poblacion_2022: int | None = None
    poblacion_2010: int | None = None
    fuente: str | None = None


class IndicadoresSociales(BaseModel):
    """Subconjunto federado de fuentes oficiales públicas por gobierno local
    (svc-datos-externos, spec-datos-externos-fuentes-oficiales.md §6). Datos
    públicos; los ve cualquier rol que vea la localidad. Porcentajes en 0–100."""

    anio_censo: int | None = None
    nbi_pct: float | None = None
    gas_red_pct: float | None = None
    agua_red_pct: float | None = None
    cloacas_pct: float | None = None
    internet_pct: float | None = None
    inquilinos_pct: float | None = None
    nbi_hacinamiento_pct: float | None = None
    calidad_iii_iv_pct: float | None = None
    hogares_hacinamiento: int | None = None
    hogares_calidad_iv: int | None = None
    desocupacion_pct: float | None = None
    cobertura_salud_pct: float | None = None
    secundario_completo_pct: float | None = None
    ips_valor: float | None = None
    ips_nivel: str | None = None
    renabap_barrios: int | None = None
    renabap_familias: int | None = None
    establecimientos_salud: int | None = None
    establecimientos_educativos: int | None = None
    vitales_anio: int | None = None
    nacimientos: int | None = None
    defunciones: int | None = None


class ResumenLocalidad(BaseModel):
    id_geo: str | None = None                      # ADR-024 — llave de join con svc-datos-externos
    localidad: str
    departamento: str | None = None
    lat_centro: float | None = None                 # centroide del padrón (viv_geo_localidades) — zoom del mapa
    lon_centro: float | None = None
    # Censo 2022 + transferencias automáticas (svc-datos-externos, ADR-025).
    # Todos None si no hubo match de id_geo o la federación está apagada/caída.
    categoria: str | None = None                   # "MU" | "CO"
    poblacion_2022: int | None = None
    viviendas_2022: int | None = None
    transferencias_periodo: str | None = None       # período del último dato cargado, ej. "2026-07-01"
    transferencias_total: float | None = None
    transferencias_por_concepto: dict[str, float] | None = None  # coparticipacion_ley_8663 | fasamu | fofindes | fondo_compensacion | bono_consenso_fiscal | total
    transferencias_per_capita: float | None = None  # ver nota en aggregations.enriquecer_con_datos_externos
    atp_monto_per_capita: float | None = None
    # Fase 1 del Tablero de Gobierno (spec-datos-externos-fase1-nomenclador-demografia.md).
    # Públicos: superficie del gobierno local y población 2010 según el Censo
    # (Estadística Córdoba, spec-datos-externos-fuentes-oficiales.md).
    superficie_km2: float | None = None
    poblacion_2010: int | None = None
    ficha_gobierno: FichaGobierno | None = None     # restringido — ver FichaGobierno
    indicadores: IndicadoresSociales | None = None  # público — fuentes oficiales (Estadística, IDECOR, RENABAP)
    programas: list[ResumenPrograma]


class ResumenTerritorialPayload(BaseModel):
    """Forma genérica del resumen — agnóstica de la fuente de cada línea.

    Spec: docs/files/spec-resumen-territorial.md §5.2
    """

    generado_para_areas: list[str]
    total_localidades: int
    total_programas: int
    localidades: list[ResumenLocalidad]
    # Denominador de "cobertura %" por departamento (padrón viv_geo_localidades,
    # ADR-024) — `localidades` de arriba sólo trae localidades con al menos un
    # programa, así que esto es lo único que permite calcular qué % del
    # departamento está cubierto. Clave = nombre de departamento tal como está
    # en el padrón (misma grafía que `ResumenLocalidad.departamento` cuando hay
    # id_geo resuelto).
    total_localidades_por_departamento: dict[str, int] = Field(default_factory=dict)
    # Dato público, igual que el denominador de arriba. `departamento` usa la
    # grafía del padrón cuando el departamento existe en él.
    zonas_rurales: list[ZonaRural] = Field(default_factory=list)


class ResumenSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payload: ResumenTerritorialPayload
    computed_at: datetime
    computed_by: str | None = None
    duracion_ms: int | None = None
