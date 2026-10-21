"""Tablero de Gobierno, Etapa 5: gestión territorial desde las planillas de Gobierno
(spec-datos-externos-fase5-gestion-territorial.md §4).

Filtro territorial por código INDEC. La cobertura (localidades visitadas sobre el total, por
municipio y comuna) usa el nomenclador como universo. Cada respuesta trae la gestión completa y
cada año, y la pantalla elige sin volver a pedir (como las Etapas 3 y 4).

Los montos de obras no salen de acá hasta que el área confirme la moneda (spec §0).
Las funciones `armar_*` son puras para poder testear cada cálculo.
"""
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_gestion.models import ExtGobConvenio, ExtGobObra, ExtGobReunion, ExtGobVisita, ExtGobVisitaGobernador
from app.gob_gestion.parse import SIN_DATO
from app.gobierno.models import ExtGobLocalidad
from app.tablero.schemas import (
    Cobertura,
    CoberturaDepartamento,
    ConvenioLocalidad,
    ConvenioResumen,
    ConvenioValor,
    ConveniosResponse,
    Conteo,
    InicioGestion,
    ObraFila,
    ObraLocalidad,
    ObrasDepartamento,
    ObrasKpis,
    ObrasResponse,
    ReunionFila,
    ReunionesAnio,
    ReunionesLocalidad,
    ReunionesPeriodo,
    ReunionesResponse,
    VisitaFila,
    VisitasAnio,
    VisitasFuncionario,
    VisitasGobernadorFila,
    VisitasGobernadorRango,
    VisitasGobernadorResponse,
    VisitasPeriodo,
    VisitasResponse,
)

SECCIONES_GESTION = ("obras", "visitas", "visitas-gobernador", "reuniones", "convenios")
_EN_EJECUCION = "OBRA EN EJECUCION"
_FINALIZADA = "FINALIZADA"
_A_EJECUTAR = "A EJECUTAR"


async def _nomenclador(db: AsyncSession, codigos: list[str] | None) -> list[ExtGobLocalidad]:
    q = select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None))
    if codigos:
        q = q.where(ExtGobLocalidad.codigo_indec.in_(codigos))
    return list((await db.execute(q)).scalars())


def _conteos(valores) -> list[Conteo]:
    return [Conteo(clave=k, cantidad=n) for k, n in Counter(valores).most_common()]


def cobertura(universo: list[ExtGobLocalidad], visitadas: set[str]) -> Cobertura:
    mu = [loc for loc in universo if loc.tipo == "MU"]
    co = [loc for loc in universo if loc.tipo == "CO"]
    return Cobertura(
        total=len(universo),
        visitadas=sum(1 for loc in universo if loc.codigo_indec in visitadas),
        municipios=len(mu),
        municipios_visitados=sum(1 for loc in mu if loc.codigo_indec in visitadas),
        comunas=len(co),
        comunas_visitadas=sum(1 for loc in co if loc.codigo_indec in visitadas),
    )


def cobertura_por_departamento(universo: list[ExtGobLocalidad], visitadas: set[str]) -> list[CoberturaDepartamento]:
    deptos: dict[str, list[ExtGobLocalidad]] = defaultdict(list)
    for loc in universo:
        deptos[loc.departamento_gob].append(loc)
    filas = [CoberturaDepartamento(departamento=d, **cobertura(ls, visitadas).model_dump()) for d, ls in deptos.items()]
    # De menor a mayor cobertura (spec del panel §2.5 #3).
    return sorted(filas, key=lambda f: (f.visitadas / f.total if f.total else 0, f.departamento))


def _mensual(fechas: list[date]) -> list[int]:
    m = [0] * 12
    for f in fechas:
        m[f.month - 1] += 1
    return m


# ── Visitas ────────────────────────────────────────────────────────────────────────


def _periodo_visitas(visitas: list[VisitaFila], universo: list[ExtGobLocalidad], anual: bool) -> VisitasPeriodo:
    tipo_de = {loc.codigo_indec: loc.tipo for loc in universo}
    visitadas = {v.codigo_indec for v in visitas}
    por_func: dict[str, list[VisitaFila]] = defaultdict(list)
    for v in visitas:
        por_func[v.funcionario or SIN_DATO].append(v)
    funcionarios = []
    for f, vs in por_func.items():
        locs = {v.codigo_indec for v in vs}
        funcionarios.append(VisitasFuncionario(
            funcionario=f,
            actividades=len(vs),
            localidades=len(locs),
            municipios=sum(1 for c in locs if tipo_de.get(c) == "MU"),
            comunas=sum(1 for c in locs if tipo_de.get(c) == "CO"),
        ))
    return VisitasPeriodo(
        visitas=len(visitas),
        cobertura=cobertura(universo, visitadas),
        por_departamento=cobertura_por_departamento(universo, visitadas),
        por_funcionario=sorted(funcionarios, key=lambda x: -x.actividades),
        por_tipo=_conteos(v.tipo or SIN_DATO for v in visitas),
        mensual=_mensual([v.fecha for v in visitas]) if anual else [],
    )


def armar_visitas(visitas: list[VisitaFila], universo: list[ExtGobLocalidad]) -> VisitasResponse:
    visitas = sorted(visitas, key=lambda v: v.fecha, reverse=True)
    anios = sorted({v.fecha.year for v in visitas})
    return VisitasResponse(
        anios=anios,
        gestion=_periodo_visitas(visitas, universo, False),
        por_anio=[VisitasAnio(anio=a, periodo=_periodo_visitas([v for v in visitas if v.fecha.year == a], universo, True)) for a in anios],
        visitas=visitas,
        ultima_fecha={o: max((v.fecha for v in visitas if v.origen == o), default=None) for o in ("funcionarios", "ministro")},
    )


async def get_visitas(db: AsyncSession, codigos: list[str] | None) -> VisitasResponse:
    universo = await _nomenclador(db, codigos)
    nombres = {loc.codigo_indec: loc for loc in universo}
    q = select(ExtGobVisita)
    if codigos:
        q = q.where(ExtGobVisita.codigo_indec.in_(codigos))
    filas = [
        VisitaFila(
            fecha=v.fecha, origen=v.origen, funcionario=v.funcionario, tipo=v.tipo, codigo_indec=v.codigo_indec,
            localidad=nombres[v.codigo_indec].nombre_gob if v.codigo_indec in nombres else v.localidad,
            departamento=nombres[v.codigo_indec].departamento_gob if v.codigo_indec in nombres else v.departamento,
        )
        for v in (await db.execute(q)).scalars()
    ]
    return armar_visitas(filas, universo)


# ── Visitas del Gobernador ─────────────────────────────────────────────────────────


def armar_visitas_gobernador(filas: list[ExtGobVisitaGobernador], universo: list[ExtGobLocalidad]) -> VisitasGobernadorResponse:
    por_codigo = {f.codigo_indec: f for f in filas}
    visitadas = {f.codigo_indec for f in filas if f.visitada}
    rangos: dict[str, list[ExtGobVisitaGobernador]] = defaultdict(list)
    lista = []
    for loc in sorted(universo, key=lambda x: (x.departamento_gob, x.nombre_gob)):
        f = por_codigo.get(loc.codigo_indec)
        rango = f.rango_habitantes if f and f.rango_habitantes else SIN_DATO
        rangos[rango].append(f)
        lista.append(VisitasGobernadorFila(
            codigo_indec=loc.codigo_indec, localidad=loc.nombre_gob, departamento=loc.departamento_gob,
            tipo=loc.tipo, visitada=loc.codigo_indec in visitadas, fecha_ultima=f.fecha_ultima if f else None,
            rango_habitantes=rango,
        ))
    return VisitasGobernadorResponse(
        cobertura=cobertura(universo, visitadas),
        por_departamento=cobertura_por_departamento(universo, visitadas),
        por_rango=[
            VisitasGobernadorRango(rango=r, total=len(fs), visitadas=sum(1 for f in fs if f and f.visitada))
            for r, fs in rangos.items()
        ],
        localidades=lista,
        con_datos=bool(filas),
    )


async def get_visitas_gobernador(db: AsyncSession, codigos: list[str] | None) -> VisitasGobernadorResponse:
    universo = await _nomenclador(db, codigos)
    q = select(ExtGobVisitaGobernador)
    if codigos:
        q = q.where(ExtGobVisitaGobernador.codigo_indec.in_(codigos))
    return armar_visitas_gobernador(list((await db.execute(q)).scalars()), universo)


# ── Reuniones ──────────────────────────────────────────────────────────────────────


def _periodo_reuniones(reuniones: list[ReunionFila], anual: bool) -> ReunionesPeriodo:
    por_loc: dict[str, list[ReunionFila]] = defaultdict(list)
    for r in reuniones:
        por_loc[r.codigo].append(r)
    return ReunionesPeriodo(
        reuniones=len(reuniones),
        localidades=len(por_loc),
        por_tema=_conteos(t for r in reuniones for t in (r.temas or [SIN_DATO])),
        por_resolucion=_conteos(r.resolucion or SIN_DATO for r in reuniones),
        mensual=_mensual([r.fecha for r in reuniones]) if anual else [],
        por_localidad=sorted(
            (
                ReunionesLocalidad(
                    codigo=c, localidad=rs[0].localidad, departamento=rs[0].departamento, reuniones=len(rs),
                    pendientes=sum(1 for r in rs if (r.resolucion or "").lower() == "pendiente"),
                    ultima=max(r.fecha for r in rs),
                )
                for c, rs in por_loc.items()
            ),
            key=lambda x: -x.reuniones,
        ),
    )


def armar_reuniones(reuniones: list[ReunionFila]) -> ReunionesResponse:
    reuniones = sorted(reuniones, key=lambda r: r.fecha, reverse=True)
    anios = sorted({r.fecha.year for r in reuniones})
    return ReunionesResponse(
        anios=anios,
        gestion=_periodo_reuniones(reuniones, False),
        por_anio=[ReunionesAnio(anio=a, periodo=_periodo_reuniones([r for r in reuniones if r.fecha.year == a], True)) for a in anios],
        reuniones=reuniones,
        ultima_fecha=reuniones[0].fecha if reuniones else None,
    )


async def get_reuniones(db: AsyncSession, codigos: list[str] | None) -> ReunionesResponse:
    nombres = {loc.codigo_indec: loc for loc in await _nomenclador(db, None)}
    q = select(ExtGobReunion)
    if codigos:
        q = q.where(ExtGobReunion.codigo_indec.in_(codigos))
    filas = []
    for r in (await db.execute(q)).scalars():
        loc = nombres.get(r.codigo_indec or "")
        filas.append(ReunionFila(
            fecha=r.fecha, codigo=r.codigo_indec or r.codigo_zona_rural or "",
            localidad=loc.nombre_gob if loc else f"Zona rural {r.codigo_zona_rural}",
            departamento=loc.departamento_gob if loc else None,
            temas=list(r.temas or []), resolucion=r.resolucion,
        ))
    return armar_reuniones(filas)


# ── Obras ──────────────────────────────────────────────────────────────────────────


def armar_obras(filas: list[ExtGobObra], codigos: list[str] | None) -> ObrasResponse:
    """Una obra por `id_obra`, con todas sus localidades. Con filtro territorial, solo las obras
    que tocan alguna localidad del filtro (las provinciales no). Sin montos (spec §0)."""
    por_obra: dict[str, list[ExtGobObra]] = defaultdict(list)
    for f in filas:
        por_obra[f.id_obra].append(f)
    filtro = set(codigos) if codigos else None
    obras: list[ObraFila] = []
    for id_obra, fs in por_obra.items():
        if filtro is not None and not any(f.codigo_indec in filtro for f in fs):
            continue
        p = fs[0]
        localidades = sorted(
            {(f.codigo_indec or f.codigo_zona_rural or "", f.localidad or "") for f in fs if f.codigo_indec or f.codigo_zona_rural},
            key=lambda x: x[1],
        )
        obras.append(ObraFila(
            id_obra=id_obra, nombre=p.nombre, ambito=p.ambito, division=p.division, estado=p.estado,
            categoria=p.categoria, avance=p.avance, fecha_inicio=p.fecha_inicio, fecha_fin=p.fecha_fin,
            departamentos=sorted({f.departamento for f in fs if f.departamento}),
            localidades=[ObraLocalidad(codigo=c, nombre=n) for c, n in localidades],
        ))
    obras.sort(key=lambda o: (o.departamentos[0] if o.departamentos else "~", o.nombre or ""))
    deptos: dict[str, list[ObraFila]] = defaultdict(list)
    for o in obras:
        for d in o.departamentos:
            deptos[d].append(o)
    avances = [o.avance for o in obras if o.avance is not None]
    return ObrasResponse(
        kpis=ObrasKpis(
            obras=len(obras),
            en_ejecucion=sum(1 for o in obras if o.categoria == _EN_EJECUCION),
            finalizadas=sum(1 for o in obras if o.categoria == _FINALIZADA),
            a_ejecutar=sum(1 for o in obras if o.categoria == _A_EJECUTAR),
            avance_promedio=sum(avances) / len(avances) if avances else None,
            localidades=len({lo.codigo for o in obras for lo in o.localidades}),
        ),
        por_estado=_conteos(o.estado or SIN_DATO for o in obras),
        por_division=_conteos(o.division or SIN_DATO for o in obras),
        por_departamento=sorted(
            (
                ObrasDepartamento(
                    departamento=d, obras=len(os_), en_ejecucion=sum(1 for o in os_ if o.categoria == _EN_EJECUCION),
                    finalizadas=sum(1 for o in os_ if o.categoria == _FINALIZADA),
                )
                for d, os_ in deptos.items()
            ),
            key=lambda x: -x.obras,
        ),
        obras=obras,
    )


async def get_obras(db: AsyncSession, codigos: list[str] | None) -> ObrasResponse:
    # El monto queda en el modelo y no pasa a la respuesta (spec §0).
    filas = list((await db.execute(select(ExtGobObra))).scalars())
    return armar_obras(filas, codigos)


# ── Convenios ──────────────────────────────────────────────────────────────────────


def armar_convenios(filas: list[ExtGobConvenio], universo: list[ExtGobLocalidad]) -> ConveniosResponse:
    nombres = {loc.codigo_indec: loc for loc in universo}
    orden: list[str] = []
    por_loc: dict[str, dict[str, ConvenioValor]] = defaultdict(dict)
    for f in filas:
        if f.codigo_indec not in nombres:
            continue
        if f.convenio not in orden:
            orden.append(f.convenio)
        por_loc[f.codigo_indec][f.convenio] = ConvenioValor(valor=f.valor, cantidad=f.cantidad, detalle=f.detalle)
    localidades = [
        ConvenioLocalidad(
            codigo_indec=c, localidad=nombres[c].nombre_gob, departamento=nombres[c].departamento_gob,
            tipo=nombres[c].tipo, valores=vs,
        )
        for c, vs in sorted(por_loc.items(), key=lambda x: (nombres[x[0]].departamento_gob, nombres[x[0]].nombre_gob))
    ]
    resumen = []
    for conv in orden:
        vals = [loc.valores.get(conv) for loc in localidades]
        resumen.append(ConvenioResumen(
            convenio=conv,
            si=sum(1 for v in vals if v and v.valor == "SI"),
            no=sum(1 for v in vals if v and v.valor == "NO"),
            nc=sum(1 for v in vals if v and v.valor == "NC"),
            sin_dato=sum(1 for v in vals if not v or v.valor is None),
            cantidad=sum(v.cantidad for v in vals if v and v.cantidad is not None) if any(v and v.cantidad is not None for v in vals) else None,
        ))
    return ConveniosResponse(convenios=orden, resumen=resumen, localidades=localidades)


async def get_convenios(db: AsyncSession, codigos: list[str] | None) -> ConveniosResponse:
    universo = await _nomenclador(db, codigos)
    q = select(ExtGobConvenio).order_by(ExtGobConvenio.id)
    if codigos:
        q = q.where(ExtGobConvenio.codigo_indec.in_(codigos))
    return armar_convenios(list((await db.execute(q)).scalars()), universo)


# ── Portada ────────────────────────────────────────────────────────────────────────


async def get_inicio_gestion(db: AsyncSession, codigos: list[str] | None) -> InicioGestion | None:
    """Bloques "Visitas en Territorio", "Reuniones en el Panal" y Gobernador de la portada, en
    toda la gestión. None si todavía no hay ninguna planilla de gestión sincronizada."""

    def filtrar(q, modelo):
        return q.where(modelo.codigo_indec.in_(codigos)) if codigos else q

    visitas = (await db.execute(filtrar(select(ExtGobVisita.codigo_indec), ExtGobVisita))).scalars().all()
    reuniones = (await db.execute(filtrar(select(ExtGobReunion.codigo_indec), ExtGobReunion))).scalars().all()
    gober = (await db.execute(filtrar(select(ExtGobVisitaGobernador.visitada), ExtGobVisitaGobernador))).scalars().all()
    if not (visitas or reuniones or gober):
        return None
    return InicioGestion(
        visitas=len(visitas),
        localidades_visitadas=len(set(visitas)),
        reuniones=len(reuniones),
        localidades_con_reunion=len({c for c in reuniones if c}),
        gobernador_visitadas=sum(1 for v in gober if v),
        gobernador_total=len(gober),
    )


async def get_seccion(db: AsyncSession, seccion: str, codigos: list[str] | None):
    if seccion == "obras":
        return await get_obras(db, codigos)
    if seccion == "visitas":
        return await get_visitas(db, codigos)
    if seccion == "visitas-gobernador":
        return await get_visitas_gobernador(db, codigos)
    if seccion == "reuniones":
        return await get_reuniones(db, codigos)
    return await get_convenios(db, codigos)
