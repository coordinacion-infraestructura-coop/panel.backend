"""Tablero de Gobierno, Etapa 3b: Fondo Federal (spec-datos-externos-fase3b-fondo-federal.md §4).

Sale de la planilla "0. Fondo Federal" del área: una fila por localidad y etapa con su estado,
el préstamo, la devolución y la rendición. Por localidad se arma lo que pidió el área: en qué
etapa está, cuáles cobró, cuáles tiene pendientes, en qué estado está la última y si debe
rendiciones.

Los valores del `0. Resumen` son del fondo entero: no se muestran con filtro territorial. Las
observaciones y el texto del aviso llevan correos y nombres: solo se devuelven a `Admin` y
`Autoridad` (spec §4.2); los demás roles ven que hay una observación y su fecha.

Como Fondo Permanente, devuelve todos los años; el año lo elige la pantalla.
"""
from collections import defaultdict
from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_fondos.models import ExtGobFfedCopa, ExtGobFfedEtapa, ExtGobFondoValor
from app.gob_fondos.parse import (
    ESTADOS_PENDIENTES_FFED,
    ESTADOS_SIN_RENDIR_FFED,
    FONDO_FEDERAL,
    FONDO_FEDERAL_COPA,
)
from app.tablero.planillas import _f, _nomenclador

ROLES_OBSERVACIONES = ("Admin", "Autoridad")
NO_ADHERIDO = "NO ADHERIDO"

# Orden fijo del embudo de estados (spec §4.1); los que aparezcan además van al final.
ORDEN_ESTADOS = (
    "PAGADO", "PAGADO SIN RENDIR", "PAGADO RENDICION OBSERVADA", "LISTO PARA PAGAR", "PEDIDO OBSERVADO",
    "DISPONIBLE", "REMANENTE DISPONIBLE", NO_ADHERIDO,
)


# ── Schemas ─────────────────────────────────────────────────────────────────────────


class FfedResumen(BaseModel):
    """`0. Resumen` de la planilla: foto de hoy del fondo entero."""

    saldo_cuenta: float | None
    disponible: float | None
    en_proceso: float | None
    deficit_superavit: float | None
    amortizaciones_restantes: float | None
    tiempo_medio_amortizacion: float | None  # meses


class FfedEstado(BaseModel):
    estado: str
    etapas: int
    localidades: int
    monto_etapa: float
    otorgado: float


class FfedAnio(BaseModel):
    anio: int
    otorgado: float
    etapas: int
    localidades: int
    mensual: list[float | None]  # 12 meses por fecha de entrega


class FfedCopa(BaseModel):
    anio: int
    aporte: float
    devolucion: float


class FfedEtapa(BaseModel):
    etapa: str
    es_extra: bool
    resolucion: str | None
    fecha_resolucion: date | None
    monto_etapa: float | None
    disponible_etapa: float | None
    estado: str | None
    ord_res: str | None
    fecha_ingreso: date | None
    sticker_pedido: str | None
    otorgado: float | None
    cuota: float | None
    plazo: int | None
    fecha_entrega: date | None
    inicio_descuento: date | None
    sticker_rendicion: str | None
    destino: str | None
    destino_detalle: str | None
    saldo: float | None
    devuelto: float | None
    cuotas_devueltas: int | None
    amortizada: bool | None
    tramite: str | None
    tiene_observacion: bool
    fecha_aviso: date | None
    # Solo Admin y Autoridad (spec §4.2); nulos para el resto.
    observaciones: str | None
    aviso_texto: str | None


class FfedPendiente(BaseModel):
    etapa: str
    estado: str
    monto: float  # lo disponible de esa etapa; si no lo trae, su monto


class FfedLocalidad(BaseModel):
    codigo_indec: str
    localidad: str
    departamento: str
    tipo: str | None
    categoria: int | None
    adherida: bool
    ultima_etapa: str | None  # la más alta habilitada para la localidad
    estado_ultima_etapa: str | None
    ultima_etapa_cobrada: str | None
    etapas_cobradas: list[str]
    pendientes: list[FfedPendiente]
    sin_rendir: list[str]
    debe_rendicion: bool
    otorgado: float
    saldo: float
    devuelto: float
    observaciones: int
    etapas: list[FfedEtapa]


class FondoFederalResponse(BaseModel):
    concepto: str = "fondo-federal"
    ver_observaciones: bool
    resumen: FfedResumen | None  # nulo con filtro territorial
    ultima_etapa_habilitada: int | None
    localidades_adheridas: int
    recibieron_ultima: int
    recibieron_anteultima: int
    deben_rendicion: int  # localidades
    con_pendientes: int  # localidades
    otorgado: float
    saldo: float
    devuelto: float
    estados: list[FfedEstado]
    anios: list[int]
    por_anio: list[FfedAnio]
    copa: list[FfedCopa]
    copa_actualizada_hasta: str | None  # `2026-08`
    localidades: list[FfedLocalidad]


# ── Cálculo ─────────────────────────────────────────────────────────────────────────


def _cobrada(e: ExtGobFfedEtapa) -> bool:
    return (e.estado or "").startswith("PAGADO")


def _clave_etapa(e: ExtGobFfedEtapa) -> tuple:
    """Orden de las etapas de una localidad: comunes por número, después las extras."""
    return (e.es_extra, e.etapa_numero if e.etapa_numero is not None else 999, e.fila)


def _etapa(e: ExtGobFfedEtapa, ver: bool) -> FfedEtapa:
    def opt(x) -> float | None:
        return float(x) if x is not None else None

    return FfedEtapa(
        etapa=e.etapa_texto, es_extra=e.es_extra, resolucion=e.resolucion, fecha_resolucion=e.fecha_resolucion,
        monto_etapa=opt(e.monto_etapa), disponible_etapa=opt(e.disponible_etapa), estado=e.estado, ord_res=e.ord_res,
        fecha_ingreso=e.fecha_ingreso, sticker_pedido=e.sticker_pedido, otorgado=opt(e.otorgado), cuota=opt(e.cuota),
        plazo=e.plazo, fecha_entrega=e.fecha_entrega, inicio_descuento=e.inicio_descuento,
        sticker_rendicion=e.sticker_rendicion, destino=e.destino, destino_detalle=e.destino_detalle, saldo=opt(e.saldo),
        devuelto=opt(e.devuelto), cuotas_devueltas=e.cuotas_devueltas, amortizada=e.amortizada, tramite=e.tramite,
        tiene_observacion=bool(e.observaciones or e.aviso_texto), fecha_aviso=e.fecha_aviso,
        observaciones=e.observaciones if ver else None, aviso_texto=e.aviso_texto if ver else None,
    )


def _localidad(codigo: str, nombre: str, depto: str, etapas: list[ExtGobFfedEtapa], ver: bool) -> FfedLocalidad:
    etapas = sorted(etapas, key=_clave_etapa)
    comunes = [e for e in etapas if not e.es_extra and e.etapa_numero is not None]
    ultima = max(comunes, key=lambda e: (e.etapa_numero, e.fila), default=None)
    cobradas = [e for e in comunes if _cobrada(e)]
    ultima_cobrada = max(cobradas, key=lambda e: (e.etapa_numero, e.fila), default=None)
    sin_rendir = [e.etapa_texto for e in etapas if e.estado in ESTADOS_SIN_RENDIR_FFED]
    primera = etapas[0]
    return FfedLocalidad(
        codigo_indec=codigo, localidad=nombre, departamento=depto, tipo=primera.tipo, categoria=primera.categoria,
        adherida=any(e.estado != NO_ADHERIDO for e in etapas),
        ultima_etapa=ultima.etapa_texto if ultima else None,
        estado_ultima_etapa=ultima.estado if ultima else None,
        ultima_etapa_cobrada=ultima_cobrada.etapa_texto if ultima_cobrada else None,
        etapas_cobradas=[e.etapa_texto for e in etapas if _cobrada(e)],
        pendientes=[
            FfedPendiente(
                etapa=e.etapa_texto, estado=e.estado or "",
                monto=_f(e.disponible_etapa) if e.disponible_etapa not in (None, 0) else _f(e.monto_etapa),
            )
            for e in etapas
            if e.estado in ESTADOS_PENDIENTES_FFED
        ],
        sin_rendir=sin_rendir,
        debe_rendicion=bool(sin_rendir),
        otorgado=sum(_f(e.otorgado) for e in etapas if _cobrada(e)),
        saldo=sum(_f(e.saldo) for e in etapas),
        devuelto=sum(_f(e.devuelto) for e in etapas),
        observaciones=sum(1 for e in etapas if e.observaciones or e.aviso_texto),
        etapas=[_etapa(e, ver) for e in etapas],
    )


def _estados(etapas: list[ExtGobFfedEtapa]) -> list[FfedEstado]:
    grupos: dict[str, list[ExtGobFfedEtapa]] = defaultdict(list)
    for e in etapas:
        grupos[e.estado or "SIN ESTADO"].append(e)
    orden = [s for s in ORDEN_ESTADOS if s in grupos] + sorted(s for s in grupos if s not in ORDEN_ESTADOS)
    return [
        FfedEstado(
            estado=s, etapas=len(grupos[s]), localidades=len({e.codigo_indec for e in grupos[s]}),
            monto_etapa=sum(_f(e.monto_etapa) for e in grupos[s]), otorgado=sum(_f(e.otorgado) for e in grupos[s]),
        )
        for s in orden
    ]


def _por_anio(etapas: list[ExtGobFfedEtapa]) -> list[FfedAnio]:
    entregadas = [e for e in etapas if _cobrada(e) and e.fecha_entrega]
    resultado = []
    for a in sorted({e.fecha_entrega.year for e in entregadas}, reverse=True):
        del_anio = [e for e in entregadas if e.fecha_entrega.year == a]
        mensual: list[float | None] = [None] * 12
        for e in del_anio:
            mensual[e.fecha_entrega.month - 1] = (mensual[e.fecha_entrega.month - 1] or 0.0) + _f(e.otorgado)
        resultado.append(FfedAnio(
            anio=a, otorgado=sum(_f(e.otorgado) for e in del_anio), etapas=len(del_anio),
            localidades=len({e.codigo_indec for e in del_anio}), mensual=mensual,
        ))
    return resultado


async def get_fondo_federal(db: AsyncSession, codigos: list[str] | None, rol: str) -> FondoFederalResponse:
    ver = rol in ROLES_OBSERVACIONES
    q = select(ExtGobFfedEtapa)
    qc = select(ExtGobFfedCopa)
    if codigos:
        q = q.where(ExtGobFfedEtapa.codigo_indec.in_(codigos))
        qc = qc.where(ExtGobFfedCopa.codigo_indec.in_(codigos))
    etapas = list((await db.execute(q.order_by(ExtGobFfedEtapa.fila))).scalars())
    nombres = {loc.codigo_indec: loc for loc in await _nomenclador(db, codigos)}

    por_loc: dict[str, list[ExtGobFfedEtapa]] = defaultdict(list)
    for e in etapas:
        por_loc[e.codigo_indec].append(e)
    # Una localidad que no está en el nomenclador se muestra con su código: el sync ya la anotó.
    localidades = sorted(
        (
            _localidad(
                c, nombres[c].nombre_gob if c in nombres else c, nombres[c].departamento_gob if c in nombres else "",
                es, ver,
            )
            for c, es in por_loc.items()
        ),
        key=lambda x: (x.departamento, x.localidad),
    )

    # La última etapa habilitada es la más alta de la provincia: con filtro se toma igual del total
    # (si no, una localidad sola parecería "al día" con su propia última etapa).
    q_ultima = select(ExtGobFfedEtapa.etapa_numero).where(ExtGobFfedEtapa.es_extra.is_(False))
    numeros = [n for n in (await db.execute(q_ultima)).scalars() if n is not None]
    ultima = max(numeros, default=None)

    def recibieron(n: int | None) -> int:
        if n is None:
            return 0
        return len({e.codigo_indec for e in etapas if not e.es_extra and e.etapa_numero == n and _cobrada(e)})

    copa: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for c in (await db.execute(qc)).scalars():
        copa[c.anio][0] += _f(c.aporte)
        copa[c.anio][1] += _f(c.devolucion)

    valores = {
        (v.fondo, v.concepto): v
        for v in (
            await db.execute(select(ExtGobFondoValor).where(ExtGobFondoValor.fondo.in_((FONDO_FEDERAL, FONDO_FEDERAL_COPA))))
        ).scalars()
    }

    def valor(concepto: str) -> float | None:
        v = valores.get((FONDO_FEDERAL, concepto))
        return float(v.monto) if v and v.monto is not None else None

    actualizada = valores.get((FONDO_FEDERAL_COPA, "actualizado_hasta"))
    resumen = None
    if not codigos and any(k[0] == FONDO_FEDERAL for k in valores):
        resumen = FfedResumen(
            saldo_cuenta=valor("saldo_cuenta"), disponible=valor("disponible"), en_proceso=valor("en_proceso"),
            deficit_superavit=valor("deficit_superavit"), amortizaciones_restantes=valor("amortizaciones_restantes"),
            tiempo_medio_amortizacion=valor("tiempo_medio_amortizacion"),
        )
    por_anio = _por_anio(etapas)
    adheridas = [loc for loc in localidades if loc.adherida]
    return FondoFederalResponse(
        ver_observaciones=ver,
        resumen=resumen,
        ultima_etapa_habilitada=ultima,
        localidades_adheridas=len(adheridas),
        recibieron_ultima=recibieron(ultima),
        recibieron_anteultima=recibieron(ultima - 1 if ultima and ultima > 1 else None),
        deben_rendicion=sum(1 for loc in localidades if loc.debe_rendicion),
        con_pendientes=sum(1 for loc in adheridas if loc.pendientes),
        otorgado=sum(loc.otorgado for loc in localidades),
        saldo=sum(loc.saldo for loc in localidades),
        devuelto=sum(loc.devuelto for loc in localidades),
        estados=_estados(etapas),
        anios=[a.anio for a in por_anio],
        por_anio=por_anio,
        copa=[FfedCopa(anio=a, aporte=m[0], devolucion=m[1]) for a, m in sorted(copa.items(), reverse=True)],
        copa_actualizada_hasta=f"{actualizada.anio}-{int(actualizada.monto):02d}" if actualizada and actualizada.anio and actualizada.monto else None,
        localidades=localidades,
    )
