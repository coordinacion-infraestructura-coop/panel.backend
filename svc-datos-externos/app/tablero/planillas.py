"""Tablero de Gobierno, Etapa 2: secciones que salen de las planillas de transferencias de
Gobierno (spec-datos-externos-fase2-transferencias.md §5, spec-tablero-gobierno-panel.md).

Filtro territorial por código INDEC, que las planillas traen en cada fila. Sin filtro se suma
todo, también los códigos que el nomenclador no tiene (mismo criterio que la Etapa 1); las
tablas por localidad muestran solo lo que cruza con el nomenclador.
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_transferencias.models import (
    ExtGobCopa,
    ExtGobEmpleados,
    ExtGobFodemep,
    ExtGobFodemepEstado,
    ExtGobFofindes,
    ExtGobFommep,
)
from app.gobierno.models import ExtGobLocalidad
from app.tablero import aggregations
from app.tablero.schemas import (
    ConceptoMonto,
    EstadoCantidad,
    FodemeepKpis,
    FodemeepLocalidad,
    FodemeepResponse,
    FommepAnio,
    FommepKpis,
    FommepLocalidad,
    FommepResponse,
    Grupo,
    Pago,
    PctSueldos,
    ResumenFila,
    ResumenResponse,
    Retencion,
    RetencionMensual,
    Retenciones,
    TransferenciasResponse,
)

_TIPOS = {"MU": "Municipio", "CO": "Comuna"}


def _f(x) -> float:
    return float(x or 0)


def _filtrar(q, modelo, codigos: list[str] | None):
    return q.where(modelo.codigo_indec.in_(codigos)) if codigos else q


async def _nomenclador(db: AsyncSession, codigos: list[str] | None) -> list[ExtGobLocalidad]:
    q = select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None))
    if codigos:
        q = q.where(ExtGobLocalidad.codigo_indec.in_(codigos))
    return list((await db.execute(q.order_by(ExtGobLocalidad.departamento_gob, ExtGobLocalidad.nombre_gob))).scalars())


# ── Coparticipación y FOFINDES ──────────────────────────────────────────────────────


async def _pagos(db: AsyncSession, modelo, anios: tuple[int, ...], codigos: list[str] | None) -> list[Pago]:
    """Un `Pago` por quincena (COPA) o por fecha de pago (FOFINDES), sumado sobre el filtro."""
    copa = modelo is ExtGobCopa
    claves = [modelo.anio, modelo.mes, modelo.quincena if copa else modelo.fecha_pago]
    q = select(
        *claves,
        func.max(modelo.fecha_pago),
        func.sum(modelo.bruto),
        func.sum(modelo.neto_a_transferir),
    ).where(modelo.anio.in_(anios)).group_by(*claves)
    filas = (await db.execute(_filtrar(q, modelo, codigos))).all()
    pagos = [
        Pago(anio=a, mes=m, quincena=k if copa else None, fecha_pago=fp, bruto=_f(b), neto=_f(n))
        for a, m, k, fp, b, n in filas
    ]
    return sorted(pagos, key=lambda p: (p.anio, p.mes, p.quincena or 0, p.fecha_pago or date.min))


def _serie(pagos: list[Pago], anio: int, campo: str) -> list[float | None]:
    serie: list[float | None] = [None] * 12
    for p in pagos:
        if p.anio == anio:
            serie[p.mes - 1] = (serie[p.mes - 1] or 0.0) + getattr(p, campo)
    return serie


def _mes_sumado(pagos: list[Pago], anio: int, mes: int) -> Pago:
    del_mes = [p for p in pagos if p.anio == anio and p.mes == mes]
    fechas = [p.fecha_pago for p in del_mes if p.fecha_pago]
    return Pago(
        anio=anio, mes=mes, fecha_pago=max(fechas) if fechas else None,
        bruto=sum(p.bruto for p in del_mes), neto=sum(p.neto for p in del_mes),
    )


def ultimo_mes_completo(pagos: list[Pago], anio: int, por_quincena: bool) -> int | None:
    """COPA: último mes del año con la segunda quincena pagada. FOFINDES: último mes con pago."""
    meses = [p.mes for p in pagos if p.anio == anio and (not por_quincena or p.quincena == 2)]
    return max(meses) if meses else None


async def _descuentos(db: AsyncSession, modelo, anio: int, codigos: list[str] | None) -> list[ConceptoMonto]:
    q = _filtrar(select(modelo.descuentos).where(modelo.anio == anio), modelo, codigos)
    totales: dict[str, float] = defaultdict(float)
    for (d,) in (await db.execute(q)).all():
        for concepto, monto in (d or {}).items():
            totales[concepto] += _f(monto)
    return sorted(
        (ConceptoMonto(concepto=c, etiqueta=c, monto=m) for c, m in totales.items() if m),
        key=lambda x: -x.monto,
    )


async def _retenciones(db: AsyncSession, anio: int, mes_ref: int | None, codigos: list[str] | None) -> Retenciones:
    q = select(
        ExtGobCopa.anio, ExtGobCopa.mes, func.sum(ExtGobCopa.bruto),
        func.sum(ExtGobCopa.caja_jubilaciones), func.sum(ExtGobCopa.apross),
    ).group_by(ExtGobCopa.anio, ExtGobCopa.mes)
    filas = (await db.execute(_filtrar(q, ExtGobCopa, codigos))).all()
    por_anio: dict[int, dict[int, tuple[float, float, float]]] = defaultdict(dict)
    for a, m, b, c, ap in filas:
        por_anio[a][m] = (_f(b), _f(c), _f(ap))

    mensual, acumulado, mismo_mes = [], [], []
    for a in sorted(por_anio):
        meses = por_anio[a]
        acum: list[tuple[float, float, float] | None] = []
        corrido = (0.0, 0.0, 0.0)
        for m in range(1, 13):
            if m in meses:
                corrido = tuple(x + y for x, y in zip(corrido, meses[m]))
                acum.append(corrido)
            else:
                acum.append(None)
        mensual.append(RetencionMensual(
            anio=a,
            caja=[aggregations.proporcion(meses[m][1], meses[m][0]) if m in meses else None for m in range(1, 13)],
            apross=[aggregations.proporcion(meses[m][2], meses[m][0]) if m in meses else None for m in range(1, 13)],
            acumulado_caja=[aggregations.proporcion(x[1], x[0]) if x else None for x in acum],
            acumulado_apross=[aggregations.proporcion(x[2], x[0]) if x else None for x in acum],
        ))
        if mes_ref is None:
            continue
        hasta = [v for m, v in meses.items() if m <= mes_ref]
        if hasta:
            b, c, ap = (sum(x[i] for x in hasta) for i in range(3))
            acumulado.append(Retencion(anio=a, caja=aggregations.proporcion(c, b), apross=aggregations.proporcion(ap, b)))
        if mes_ref in meses:
            b, c, ap = meses[mes_ref]
            mismo_mes.append(Retencion(anio=a, caja=aggregations.proporcion(c, b), apross=aggregations.proporcion(ap, b)))
    return Retenciones(mes_referencia=mes_ref, mensual=mensual, acumulado=acumulado, mismo_mes=mismo_mes)


async def _pct_sueldos(db: AsyncSession, anio: int, mes: int | None, codigos: list[str] | None) -> PctSueldos | None:
    """Spec Fase 2 §5.1. Numerador y denominador solo con las localidades que tienen masa
    salarial; la masa nunca sale de esta función."""
    if mes is None:
        return None
    q = _filtrar(
        select(ExtGobEmpleados.anio, ExtGobEmpleados.codigo_indec, ExtGobEmpleados.masa_salarial).where(
            ExtGobEmpleados.masa_salarial.is_not(None)
        ),
        ExtGobEmpleados, codigos,
    )
    filas = (await db.execute(q)).all()
    if not filas and not (await db.execute(select(func.count()).select_from(ExtGobEmpleados))).scalar_one():
        return None  # la planilla de empleados todavía no se sincronizó
    anios = sorted({a for a, _c, _m in filas})
    anio_masa = max((a for a in anios if a <= anio), default=anios[-1]) if anios else None
    masa = {c: _f(m) for a, c, m in filas if a == anio_masa}

    async def _suma(modelo) -> tuple[float, float, int]:
        r = (await db.execute(
            select(func.sum(modelo.bruto), func.sum(modelo.neto_a_transferir), func.count()).where(
                modelo.anio == anio, modelo.mes == mes, modelo.codigo_indec.in_(list(masa))
            )
        )).one()
        return _f(r[0]), _f(r[1]), r[2]

    copa_b, copa_n, _ = await _suma(ExtGobCopa)
    fof_b, fof_n, fof_filas = await _suma(ExtGobFofindes)
    total_masa = sum(masa.values())
    localidades = len(codigos) if codigos else len((await db.execute(
        select(ExtGobLocalidad.codigo_indec).where(ExtGobLocalidad.deleted_at.is_(None))
    )).all())
    return PctSueldos(
        bruto=aggregations.proporcion(total_masa, copa_b + fof_b),
        neto=aggregations.proporcion(total_masa, copa_n + fof_n),
        anio_masa=anio_masa,
        mes_referencia=date(anio, mes, 1),
        localidades_con_dato=len(masa),
        localidades=localidades,
        incluye_fofindes=fof_filas > 0,
    )


async def enriquecer_transferencias(
    db: AsyncSession, seccion: str, anio: int, codigos: list[str] | None, base: TransferenciasResponse
) -> TransferenciasResponse:
    """Sobre la respuesta de Transparencia (Etapa 1), pone los datos de la planilla cuando
    tiene el año pedido. Si no lo tiene, devuelve la base con `fuente="transparencia"`."""
    copa = seccion == "coparticipacion"
    modelo = ExtGobCopa if copa else ExtGobFofindes
    pagos = await _pagos(db, modelo, (anio - 1, anio), codigos)
    if not any(p.anio == anio for p in pagos):
        return base

    serie = _serie(pagos, anio, "bruto")
    neto = _serie(pagos, anio, "neto")
    planilla_ant = any(p.anio == anio - 1 for p in pagos)
    serie_ant = _serie(pagos, anio - 1, "bruto") if planilla_ant else base.mensual_anterior
    mes = aggregations.ultimo_mes_con_dato(serie)
    total = aggregations.acumulado(serie, mes)
    acum_ant = aggregations.acumulado(serie_ant, mes) if mes is not None else None

    del_anio = [p for p in pagos if p.anio == anio]
    ultimo = max(del_anio, key=lambda p: (p.fecha_pago or date(p.anio, p.mes, 1), p.mes, p.quincena or 0))
    mes_completo = ultimo_mes_completo(pagos, anio, por_quincena=copa)
    localidades = (await db.execute(
        _filtrar(
            select(func.count(func.distinct(modelo.codigo_indec))).where(modelo.anio == anio, modelo.bruto > 0),
            modelo, codigos,
        )
    )).scalar_one()

    return base.model_copy(update={
        "fuente": "planilla",
        "fuente_anterior": "planilla" if planilla_ant else "transparencia",
        "ultimo_periodo": date(anio, mes + 1, 1) if mes is not None else None,
        "total_anio": total,
        "acumulado_anterior": acum_ant or None,
        "variacion": aggregations.variacion(total, acum_ant),
        "ultimo_mes": serie[mes] if mes is not None else None,
        "mensual": serie,
        "mensual_anterior": serie_ant,
        "localidades": localidades,
        "total_neto_anio": aggregations.acumulado(neto, mes),
        "mensual_neto": neto,
        "ultimo_pago": ultimo,
        "ultimo_mes_completo": _mes_sumado(pagos, anio, mes_completo) if mes_completo else None,
        "pagos": del_anio,
        "descuentos": await _descuentos(db, modelo, anio, codigos),
        "retenciones": await _retenciones(db, anio, mes_completo or (mes + 1 if mes is not None else None), codigos) if copa else None,
        "pct_sueldos": await _pct_sueldos(db, anio, mes_completo, codigos) if copa else None,
    })


# ── FODEMEEP ────────────────────────────────────────────────────────────────────────


async def get_fodemeep(db: AsyncSession, anio: int, codigos: list[str] | None) -> FodemeepResponse:
    filas = (await db.execute(_filtrar(
        select(
            ExtGobFodemep.codigo_indec, ExtGobFodemep.periodo, ExtGobFodemep.presupuestado,
            ExtGobFodemep.acumulado, ExtGobFodemep.neto_a_transferir,
        ),
        ExtGobFodemep, codigos,
    ))).all()

    con_fondo = {c for c, _p, pres, _a, n in filas if _f(pres) > 0 or _f(n) > 0}
    periodos = sorted({p for _c, p, *_ in filas if p <= date(anio, 12, 31)})
    ultimo = periodos[-1] if periodos else None
    del_ultimo = [f for f in filas if f[1] == ultimo]

    mensual = {k: [None] * 12 for k in ("transferido", "retenido", "presupuestado")}
    por_loc: dict[str, list[float | None]] = defaultdict(lambda: [None] * 12)
    for c, p, pres, acum, n in filas:
        if p.year != anio:
            continue
        i = p.month - 1
        for clave, valor in (("transferido", n), ("retenido", acum), ("presupuestado", pres)):
            if valor is not None:
                mensual[clave][i] = (mensual[clave][i] or 0.0) + _f(valor)
        if n is not None:
            por_loc[c][i] = (por_loc[c][i] or 0.0) + _f(n)

    locs = await _nomenclador(db, codigos)
    estados = dict((await db.execute(select(ExtGobFodemepEstado.codigo_indec, ExtGobFodemepEstado.estado))).all())
    conteo: dict[str, int] = defaultdict(int)
    for loc in locs:
        conteo[estados.get(loc.codigo_indec) or "SIN DATO"] += 1

    return FodemeepResponse(
        anio=anio,
        kpis=FodemeepKpis(
            localidades=len(con_fondo),
            presupuestado_gestion=sum(_f(f[2]) for f in filas),
            transferido_gestion=sum(_f(f[4]) for f in filas),
            ultimo_periodo=ultimo,
            presupuestado_ultimo=sum(_f(f[2]) for f in del_ultimo) if ultimo else None,
            transferido_ultimo=sum(_f(f[4]) for f in del_ultimo) if ultimo else None,
            retenido_ultimo=sum(_f(f[3]) for f in del_ultimo) if ultimo else None,
        ),
        mensual_transferido=mensual["transferido"],
        mensual_retenido=mensual["retenido"],
        mensual_presupuestado=mensual["presupuestado"],
        por_localidad=[
            FodemeepLocalidad(
                codigo_indec=loc.codigo_indec, localidad=loc.nombre_gob, departamento=loc.departamento_gob,
                estado=estados.get(loc.codigo_indec), meses=por_loc[loc.codigo_indec],
                total=sum(v for v in por_loc[loc.codigo_indec] if v is not None),
            )
            for loc in locs
            if loc.codigo_indec in por_loc
        ],
        estados=[EstadoCantidad(estado=e, cantidad=n) for e, n in sorted(conteo.items(), key=lambda x: -x[1])],
    )


# ── FOMMEP ──────────────────────────────────────────────────────────────────────────


def _kpis_fommep(filas: list[ExtGobFommep]) -> FommepKpis:
    def grupo(cant: str, monto: str) -> Grupo:
        return Grupo(cantidad=sum(getattr(f, cant) or 0 for f in filas), monto=sum(_f(getattr(f, monto)) for f in filas))

    moviles = grupo("cant_moviles", "monto_moviles")
    edificios = grupo("cant_edificios_total", "monto_edificios_total")
    total = sum(_f(f.monto_total) for f in filas)
    return FommepKpis(
        localidades=len({f.codigo_indec for f in filas if _f(f.monto_total) > 0}),
        monto_total=total,
        moviles=moviles,
        edificios_a=grupo("cant_edificios_a", "monto_edificios_a"),
        edificios_b=grupo("cant_edificios_b", "monto_edificios_b"),
        edificios_c=grupo("cant_edificios_c", "monto_edificios_c"),
        edificios=edificios,
        otros=total - moviles.monto - edificios.monto,
    )


async def get_fommep(db: AsyncSession, codigos: list[str] | None) -> FommepResponse:
    """Todos los años y la gestión completa; el filtro de año es propio de la pantalla."""
    filas = list((await db.execute(_filtrar(select(ExtGobFommep), ExtGobFommep, codigos))).scalars())
    anios = sorted({f.anio for f in filas}, reverse=True)
    nombres = {loc.codigo_indec: loc for loc in await _nomenclador(db, codigos)}
    return FommepResponse(
        anios=anios,
        gestion=_kpis_fommep(filas) if filas else None,
        por_anio=[FommepAnio(anio=a, kpis=_kpis_fommep([f for f in filas if f.anio == a])) for a in anios],
        por_localidad=sorted(
            (
                FommepLocalidad(
                    anio=f.anio, codigo_indec=f.codigo_indec, localidad=nombres[f.codigo_indec].nombre_gob,
                    departamento=nombres[f.codigo_indec].departamento_gob,
                    cant_moviles=f.cant_moviles or 0, monto_moviles=_f(f.monto_moviles),
                    cant_edificios=f.cant_edificios_total or 0, monto_edificios=_f(f.monto_edificios_total),
                    monto_total=_f(f.monto_total),
                )
                for f in filas
                if f.codigo_indec in nombres and _f(f.monto_total) > 0
            ),
            key=lambda x: (x.departamento, x.localidad, x.anio),
        ),
    )


# ── Resumen general (COPA + FOFINDES, spec Fase 2 §5.2) ─────────────────────────────


async def get_resumen(db: AsyncSession, anio: int, codigos: list[str] | None, poblacion: dict[str, int]) -> ResumenResponse:
    async def neto_por_codigo(modelo) -> dict[str, float]:
        q = select(modelo.codigo_indec, func.sum(modelo.neto_a_transferir)).where(modelo.anio == anio).group_by(modelo.codigo_indec)
        return {c: _f(s) for c, s in (await db.execute(_filtrar(q, modelo, codigos))).all()}

    copa = await neto_por_codigo(ExtGobCopa)
    fofindes = await neto_por_codigo(ExtGobFofindes)
    ultimo_mes = (await db.execute(_filtrar(select(func.max(ExtGobCopa.mes)).where(ExtGobCopa.anio == anio), ExtGobCopa, codigos))).scalar_one()
    locs = await _nomenclador(db, codigos)

    def fila(clave: str, departamento: str, ls: list[ExtGobLocalidad], c: float, fo: float, **extra) -> ResumenFila:
        pob = sum(poblacion.get(loc.codigo_indec, 0) for loc in ls)
        return ResumenFila(
            clave=clave, departamento=departamento, localidades=len(ls), poblacion=pob,
            copa=c, fofindes=fo, total=c + fo, por_habitante=aggregations.por_habitante(c + fo, pob), **extra,
        )

    por_localidad = [
        fila(loc.codigo_indec, loc.departamento_gob, [loc], copa.get(loc.codigo_indec, 0.0), fofindes.get(loc.codigo_indec, 0.0),
             localidad=loc.nombre_gob, tipo=_TIPOS.get(loc.tipo or ""))
        for loc in locs
    ]
    deptos: dict[str, list[ExtGobLocalidad]] = defaultdict(list)
    for loc in locs:
        deptos[loc.departamento_gob].append(loc)
    por_departamento = [
        fila(d, d, ls, sum(copa.get(x.codigo_indec, 0.0) for x in ls), sum(fofindes.get(x.codigo_indec, 0.0) for x in ls))
        for d, ls in sorted(deptos.items())
    ]
    # Total: sin filtro suma todo lo de la planilla, también códigos fuera del nomenclador.
    total = fila("total", "Total", locs, sum(copa.values()), sum(fofindes.values()))
    return ResumenResponse(
        anio=anio,
        periodo_hasta=date(anio, ultimo_mes, 1) if ultimo_mes else None,
        total=total,
        por_departamento=por_departamento,
        por_localidad=por_localidad,
    )
