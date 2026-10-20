"""Tablero de Gobierno, Etapa 3: Fondo Permanente, Fondo Ambiental y Comunidades Regionales
(spec-datos-externos-fase3-fondos.md §4).

Como FOMMEP, cada sección devuelve todos los años y la gestión completa; el año lo elige la
pantalla. Filtro territorial por código INDEC. Las comunidades regionales no son localidades:
entran por departamento (el de las localidades filtradas). Los valores que son del fondo entero
(saldo en cuenta, ingresos, crédito vigente) no se muestran con filtro territorial.
"""
import re
from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_fondos.models import (
    ExtGobCregCuota,
    ExtGobFondoAmbiental,
    ExtGobFondoValor,
    ExtGobFpermEtapa,
    ExtGobFpermLocalidad,
    ExtGobFpermPrestamo,
)
from app.gob_fondos.parse import COMUNIDADES_REGIONALES, FONDO_AMBIENTAL, FONDO_PERMANENTE, sin_tildes
from app.gobierno.models import ExtGobEnte, ExtGobLocalidad
from app.tablero.planillas import _f, _nomenclador
from app.tablero.schemas import (
    ComunidadesRegionalesResponse,
    CregAnio,
    CregCuota,
    CregKpis,
    CregTipo,
    EstadoMonto,
    FondoAmbientalAnio,
    FondoAmbientalFila,
    FondoAmbientalKpis,
    FondoAmbientalResponse,
    FondoPermanenteResponse,
    FpermAnio,
    FpermLocalidad,
    FpermPrestamo,
    ObjetoMonto,
    PrestamosKpis,
)

# Estados que el Looker muestra siempre, aunque estén en cero (relevamiento §2.13).
ESTADOS_FONDO_AMBIENTAL = ("PAGADO", "LISTO PARA PAGAR", "TRIBUNAL DE CUENTAS", "EN TRAMITE")


def _norm(texto: str | None) -> str:
    return re.sub(r"\s+", " ", sin_tildes(texto or "").upper()).strip()


async def _valores(db: AsyncSession, fondo: str) -> dict[tuple[str, int | None], float]:
    filas = (await db.execute(select(ExtGobFondoValor).where(ExtGobFondoValor.fondo == fondo))).scalars()
    return {(v.concepto, v.anio): _f(v.monto) for v in filas}


async def _comunidades(db: AsyncSession, codigos: list[str] | None) -> tuple[dict[str, ExtGobEnte], list[str] | None]:
    """Comunidades regionales del nomenclador y, con filtro, los departamentos de las
    localidades filtradas. Sin filtro devuelve `None` como departamentos."""
    entes = {
        e.codigo: e
        for e in (
            await db.execute(select(ExtGobEnte).where(ExtGobEnte.deleted_at.is_(None), ExtGobEnte.tipo_ente == "comunidad_regional"))
        ).scalars()
    }
    if not codigos:
        return entes, None
    deptos = sorted({loc.departamento_gob for loc in await _nomenclador(db, codigos)})
    return entes, deptos


def _ente_en(ente: ExtGobEnte | None, deptos: list[str] | None, departamento_planilla: str | None = None) -> bool:
    """Un ente entra si su departamento es uno de los filtrados. Los entes que no están en el
    nomenclador usan el de la planilla, que puede nombrar varios (`SAN ALBERTO / SAN JAVIER`)."""
    if deptos is None:
        return True
    buscados = {_norm(d) for d in deptos}
    if ente is not None:
        return _norm(ente.departamento) in buscados
    return any(_norm(d) in buscados for d in (departamento_planilla or "").split("/"))


def _estados(filas: Iterable[tuple[str | None, float]], fijos: tuple[str, ...] = ()) -> list[EstadoMonto]:
    conteo: dict[str, list[float]] = {e: [] for e in fijos}
    for estado, monto in filas:
        conteo.setdefault(_norm(estado) or "SIN ESTADO", []).append(monto)
    return [EstadoMonto(estado=e, cantidad=len(m), monto=sum(m)) for e, m in conteo.items()]


# ── Fondo Permanente ───────────────────────────────────────────────────────────────


def _kpis_prestamos(prestamos: list[ExtGobFpermPrestamo]) -> PrestamosKpis:
    return PrestamosKpis(
        monto=sum(_f(p.monto_total) for p in prestamos),
        prestamos=len(prestamos),
        localidades=len({p.codigo_indec for p in prestamos if p.codigo_indec}),
    )


async def get_fondo_permanente(db: AsyncSession, codigos: list[str] | None) -> FondoPermanenteResponse:
    def filtrar(q, modelo):
        return q.where(modelo.codigo_indec.in_(codigos)) if codigos else q

    locs = list((await db.execute(filtrar(select(ExtGobFpermLocalidad), ExtGobFpermLocalidad))).scalars())
    etapas: dict[str, list[ExtGobFpermEtapa]] = defaultdict(list)
    for e in (await db.execute(filtrar(select(ExtGobFpermEtapa), ExtGobFpermEtapa))).scalars():
        etapas[e.codigo_indec].append(e)
    prestamos = list((await db.execute(filtrar(select(ExtGobFpermPrestamo), ExtGobFpermPrestamo))).scalars())
    valores = await _valores(db, FONDO_PERMANENTE)
    nombres = {loc.codigo_indec: loc for loc in await _nomenclador(db, codigos)}

    otorgados = [p for p in prestamos if p.fecha]
    anios = sorted({p.fecha.year for p in otorgados}, reverse=True)
    por_anio = []
    for a in anios:
        del_anio = [p for p in otorgados if p.fecha.year == a]
        mensual: list[float | None] = [None] * 12
        for p in del_anio:
            mensual[p.fecha.month - 1] = (mensual[p.fecha.month - 1] or 0.0) + _f(p.monto_total)
        por_anio.append(FpermAnio(anio=a, otorgado=_kpis_prestamos(del_anio), mensual=mensual))

    def fila_prestamo(p: ExtGobFpermPrestamo) -> FpermPrestamo:
        loc = nombres.get(p.codigo_indec or "")
        return FpermPrestamo(
            anio=p.fecha.year if p.fecha else None, codigo_indec=p.codigo_indec,
            localidad=loc.nombre_gob if loc else None, departamento=loc.departamento_gob if loc else None,
            etapas=p.etapas_texto, fecha=p.fecha, monto_total=_f(p.monto_total), cuota=float(p.cuota) if p.cuota is not None else None,
            plazo=p.plazo, mes_inicio_descuento=p.mes_inicio_descuento, destino=p.destino, ord_res=p.ord_res,
        )

    filas_loc = sorted(
        (
            FpermLocalidad(
                codigo_indec=loc.codigo_indec, localidad=nombres[loc.codigo_indec].nombre_gob,
                departamento=nombres[loc.codigo_indec].departamento_gob, ultima_etapa=loc.ultima_etapa,
                recibio_ultima=loc.recibio_ultima, recibio_anteultima=loc.recibio_anteultima,
                etapas_disponibles=sorted(e.etapa for e in etapas.get(loc.codigo_indec, [])),
                disponible=sum(_f(e.monto) for e in etapas.get(loc.codigo_indec, [])),
            )
            for loc in locs
            if loc.codigo_indec in nombres
        ),
        key=lambda x: (x.departamento, x.localidad),
    )
    ultima = valores.get(("ultima_etapa_habilitada", None))
    return FondoPermanenteResponse(
        ultima_etapa_habilitada=int(ultima) if ultima is not None else None,
        saldo_cuenta=None if codigos else valores.get(("saldo_cuenta", None)),
        localidades_adheridas=len(locs),
        recibieron_ultima=sum(1 for loc in locs if loc.recibio_ultima),
        recibieron_anteultima=sum(1 for loc in locs if loc.recibio_anteultima),
        disponible=sum(_f(e.monto) for es in etapas.values() for e in es),
        localidades_con_disponible=sum(1 for es in etapas.values() if any(_f(e.monto) > 0 for e in es)),
        listo_para_pagar=_kpis_prestamos([p for p in prestamos if not p.fecha]),
        anios=anios,
        gestion=_kpis_prestamos(otorgados),
        por_anio=por_anio,
        prestamos=sorted((fila_prestamo(p) for p in prestamos), key=lambda x: (x.fecha is not None, x.fecha), reverse=True),
        localidades=filas_loc,
    )


# ── Fondo Ambiental ────────────────────────────────────────────────────────────────


def objeto_base(objeto: str | None) -> str:
    """Agrupa variantes: sin código de glosario `(21)`, sin tildes, en mayúsculas."""
    return _norm(re.sub(r"\(\d+\)", " ", objeto or "")) or "SIN OBJETO"


def _kpis_ambiental(filas: list[ExtGobFondoAmbiental], ingresos: float | None) -> FondoAmbientalKpis:
    afectado = sum(_f(f.monto) for f in filas)
    return FondoAmbientalKpis(
        localidades=len({f.codigo_indec for f in filas if f.codigo_indec}),
        # El código `500` lo comparten varios entes intermunicipales: se cuentan por nombre.
        entes=len({(f.codigo_ente, f.nombre_ente if f.codigo_ente == "500" else None) for f in filas if f.codigo_ente}),
        convenios=len(filas),
        afectado=afectado,
        pagado=sum(_f(f.monto) for f in filas if _norm(f.estado) == "PAGADO"),
        ingresos=ingresos,
        disponible=ingresos - afectado if ingresos is not None else None,
        estados=_estados(((f.estado, _f(f.monto)) for f in filas), ESTADOS_FONDO_AMBIENTAL),
    )


async def get_fondo_ambiental(db: AsyncSession, codigos: list[str] | None) -> FondoAmbientalResponse:
    entes, deptos = await _comunidades(db, codigos)
    nombres = {loc.codigo_indec: loc for loc in await _nomenclador(db, codigos)}
    filas = [
        f
        for f in (await db.execute(select(ExtGobFondoAmbiental))).scalars()
        if (f.codigo_indec and (not codigos or f.codigo_indec in codigos))
        or (f.codigo_ente and _ente_en(entes.get(f.codigo_ente), deptos, f.departamento_ente))
    ]
    ingresos = {a: m for (c, a), m in (await _valores(db, FONDO_AMBIENTAL)).items() if c == "ingresos"}
    anios = sorted({f.anio for f in filas if f.anio}, reverse=True)

    def ingreso(anios_: Iterable[int]) -> float | None:
        if codigos or not ingresos:
            return None
        return sum(ingresos.get(a, 0.0) for a in anios_)

    objetos: dict[str, list[float]] = defaultdict(list)
    for f in filas:
        objetos[objeto_base(f.objeto)].append(_f(f.monto))

    def fila(f: ExtGobFondoAmbiental) -> FondoAmbientalFila:
        if f.codigo_ente:
            ente = entes.get(f.codigo_ente)
            nombre, depto = (ente.nombre, ente.departamento) if ente else (f.nombre_ente or f.codigo_ente, f.departamento_ente)
        else:
            loc = nombres.get(f.codigo_indec or "")
            nombre, depto = (loc.nombre_gob, loc.departamento_gob) if loc else (f.codigo_indec or "", None)
        return FondoAmbientalFila(
            anio=f.anio, codigo=f.codigo_ente or f.codigo_indec or "", es_ente=bool(f.codigo_ente), localidad=nombre,
            departamento=depto, expediente=f.expediente, convenio=f.convenio, fecha_convenio=f.fecha_convenio,
            resolucion=f.resolucion, objeto=f.objeto, monto=_f(f.monto), estado=f.estado, fecha_estado=f.fecha_estado,
        )

    return FondoAmbientalResponse(
        anios=anios,
        gestion=_kpis_ambiental(filas, ingreso(ingresos)) if filas else None,
        por_anio=[FondoAmbientalAnio(anio=a, kpis=_kpis_ambiental([f for f in filas if f.anio == a], ingreso([a]))) for a in anios],
        objetos=sorted(
            (ObjetoMonto(objeto=o, cantidad=len(m), monto=sum(m)) for o, m in objetos.items()), key=lambda x: -x.monto
        )[:15],
        convenios=sorted((fila(f) for f in filas), key=lambda x: (x.departamento or "", x.localidad, x.anio or 0)),
    )


# ── Comunidades Regionales ─────────────────────────────────────────────────────────


def _es_obra(tipo: str | None) -> bool:
    return _norm(tipo).startswith("OBRA")


def _anulada(c: ExtGobCregCuota) -> bool:
    return _norm(c.estado) == "ANULADO"


def _tipo(cuotas: list[ExtGobCregCuota], credito: float | None) -> CregTipo:
    vigentes = [c for c in cuotas if not _anulada(c)]
    monto = sum(_f(c.monto_cuota) for c in vigentes)
    pagado = sum(_f(c.monto_cuota) for c in vigentes if _norm(c.estado).startswith("PAGADO"))
    return CregTipo(
        credito=credito, cuotas=len(vigentes), monto_cuotas=monto, pagado=pagado, a_pagar=monto - pagado,
        saldo=credito - monto if credito is not None else None,
    )


def _kpis_creg(cuotas: list[ExtGobCregCuota], credito_func: float | None, credito_obras: float | None) -> CregKpis:
    func_ = [c for c in cuotas if not _es_obra(c.tipo)]
    obras = [c for c in cuotas if _es_obra(c.tipo)]
    total_credito = credito_func + credito_obras if credito_func is not None and credito_obras is not None else None
    return CregKpis(
        funcionamiento=_tipo(func_, credito_func),
        obras=_tipo(obras, credito_obras),
        total=_tipo(cuotas, total_credito),
        comunidades=len({c.codigo_ente for c in cuotas if c.codigo_ente}),
        estados=_estados((c.estado, _f(c.monto_cuota)) for c in cuotas),
    )


async def get_comunidades_regionales(db: AsyncSession, codigos: list[str] | None) -> ComunidadesRegionalesResponse:
    entes, deptos = await _comunidades(db, codigos)
    cuotas = [c for c in (await db.execute(select(ExtGobCregCuota))).scalars() if _ente_en(entes.get(c.codigo_ente or ""), deptos)]
    valores = await _valores(db, COMUNIDADES_REGIONALES)
    anios = sorted({c.anio for c in cuotas if c.anio} | ({a for (_c, a) in valores if a} if not codigos else set()), reverse=True)

    def credito(concepto: str, anios_: Iterable[int]) -> float | None:
        if codigos:
            return None
        return sum(valores.get((concepto, a), 0.0) for a in anios_)

    def fila(c: ExtGobCregCuota) -> CregCuota:
        ente = entes.get(c.codigo_ente or "")
        return CregCuota(
            anio=c.anio, codigo_ente=c.codigo_ente or "", comunidad=ente.nombre if ente else (c.codigo_ente or ""),
            departamento=ente.departamento if ente else None, tipo=c.tipo, expediente=c.expediente, destino=c.destino,
            monto=float(c.monto) if c.monto is not None else None, cuota=c.cuota,
            monto_cuota=float(c.monto_cuota) if c.monto_cuota is not None else None, estado=c.estado,
            fecha_pago=c.fecha_pago, fecha_rendicion=c.fecha_rendicion,
        )

    return ComunidadesRegionalesResponse(
        departamentos=deptos,
        anios=anios,
        gestion=_kpis_creg(cuotas, credito("credito_funcionamiento", anios), credito("credito_obras", anios)) if cuotas else None,
        por_anio=[
            CregAnio(
                anio=a,
                kpis=_kpis_creg([c for c in cuotas if c.anio == a], credito("credito_funcionamiento", [a]), credito("credito_obras", [a])),
            )
            for a in anios
        ],
        cuotas=sorted((fila(c) for c in cuotas), key=lambda x: (-(x.anio or 0), x.departamento or "", x.comunidad, x.cuota or 0)),
    )
