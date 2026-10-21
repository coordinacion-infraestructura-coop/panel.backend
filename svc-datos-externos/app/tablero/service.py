"""Tablero de Gobierno (spec-tablero-gobierno-panel.md §3.3, Etapa 0).

`get_meta` arma lo que necesita la barra común del tablero: las localidades del nomenclador
de Gobierno para los filtros, los años con datos y la frescura de cada fuente. Cada sección
suma su función (Etapa 1: Inicio y transferencias automáticas); los cálculos viven en
`aggregations.py`.
"""
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.gob_transferencias import sync as gob_transferencias_sync
from app.gob_transferencias.models import ExtGobCopa
from app.gobierno import sync as gobierno_sync
from app.gobierno.models import ExtGobLocalidad
from app.integrations import atp_interno
from app.tablero import aggregations, fondos, gestion, planillas
from app.tablero.schemas import (
    ConceptoMonto,
    FodemeepResponse,
    FommepResponse,
    FuenteFrescura,
    InicioDepartamento,
    InicioKpis,
    InicioResponse,
    LocalidadFiltro,
    ResumenResponse,
    TableroMetaResponse,
    TransferenciasResponse,
)
from app.transferencias.models import ExtTransferencia, ExtTransferenciaSyncLog

_TIPOS = {"MU": "Municipio", "CO": "Comuna"}
_ETIQUETAS_GOB = {
    gobierno_sync.FUENTE_NOMENCLADOR: "Nomenclador de localidades (Gobierno)",
    gobierno_sync.FUENTE_VISTA: "0. Resumen General - Vista (Gobierno)",
}


async def _localidades(db: AsyncSession) -> list[LocalidadFiltro]:
    filas = (
        await db.execute(
            select(ExtGobLocalidad)
            .where(ExtGobLocalidad.deleted_at.is_(None))
            .order_by(ExtGobLocalidad.departamento_gob, ExtGobLocalidad.nombre_gob)
        )
    ).scalars()
    return [
        LocalidadFiltro(
            id_geo=loc.id_geo,
            codigo_indec=loc.codigo_indec,
            nombre=loc.nombre_gob,
            departamento=loc.departamento_gob,
            tipo=_TIPOS.get(loc.tipo or ""),
        )
        for loc in filas
    ]


async def _anios(db: AsyncSession) -> list[int]:
    """Años con transferencias cargadas, más el año en curso; del más nuevo al más viejo."""
    periodos = (await db.execute(select(ExtTransferencia.periodo).distinct())).scalars()
    anios = {p.year for p in periodos if p is not None}
    anios |= set((await db.execute(select(ExtGobCopa.anio).distinct())).scalars())
    anios.add(datetime.now(timezone.utc).year)
    return sorted(anios, reverse=True)


async def _frescura(db: AsyncSession) -> list[FuenteFrescura]:
    fuentes: list[FuenteFrescura] = []

    logs = {log.fuente: log for log in await gobierno_sync.get_sync_estado(db)}
    for fuente, etiqueta in _ETIQUETAS_GOB.items():
        log = logs.get(fuente)
        fuentes.append(
            FuenteFrescura(
                fuente=fuente,
                etiqueta=etiqueta,
                estado=log.estado if log else "sin_datos",
                ultima_corrida=log.corrida_en if log else None,
                detalle=f"{log.filas_upsert} filas" if log else None,
            )
        )

    logs_planillas = {log.fuente: log for log in await gob_transferencias_sync.get_sync_estado(db)}
    for fuente, etiqueta in gob_transferencias_sync.ETIQUETAS.items():
        log = logs_planillas.get(fuente)
        fuentes.append(
            FuenteFrescura(
                fuente=fuente,
                etiqueta=etiqueta,
                estado=log.estado if log else "sin_datos",
                ultima_corrida=log.corrida_en if log else None,
                detalle=f"{log.filas_upsert} filas" if log else None,
            )
        )

    ultimo_log = (
        await db.execute(
            select(ExtTransferenciaSyncLog).order_by(ExtTransferenciaSyncLog.corrida_en.desc()).limit(1)
        )
    ).scalar_one_or_none()
    ultimo_periodo = (await db.execute(select(func.max(ExtTransferencia.periodo)))).scalar_one_or_none()
    fuentes.append(
        FuenteFrescura(
            fuente="transferencias",
            etiqueta="Transferencias a municipios y comunas (Transparencia)",
            estado="ok" if ultimo_log else "sin_datos",
            ultima_corrida=ultimo_log.corrida_en if ultimo_log else None,
            ultimo_periodo=ultimo_periodo,
        )
    )

    censo = (
        await db.execute(select(func.count()).select_from(ExtGeoCenso).where(ExtGeoCenso.deleted_at.is_(None)))
    ).scalar_one()
    fuentes.append(
        FuenteFrescura(
            fuente="censo_2022",
            etiqueta="Censo 2022 (INDEC)",
            estado="ok" if censo else "sin_datos",
            ultima_corrida=None,
            detalle=f"carga única · {censo} gobiernos locales" if censo else None,
        )
    )
    return fuentes


async def get_meta(db: AsyncSession) -> TableroMetaResponse:
    return TableroMetaResponse(
        localidades=await _localidades(db),
        anios=await _anios(db),
        frescura=await _frescura(db),
    )


# ── Filtro territorial ──────────────────────────────────────────────────────────
# El tablero filtra por código INDEC (la clave del nomenclador de Gobierno, siempre presente);
# las transferencias se cruzan por id_geo, así que se traduce acá.


async def _nomenclador(db: AsyncSession, codigos: list[str] | None) -> list[ExtGobLocalidad]:
    q = select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None))
    if codigos:
        q = q.where(ExtGobLocalidad.codigo_indec.in_(codigos))
    return list((await db.execute(q)).scalars())


def _transferencias_filtradas(conceptos: list[str], ids_geo: set[str] | None, anios: tuple[int, ...]):
    """Sin filtro (ids_geo None) se toma todo, también las filas sin vínculo al padrón, para
    que el total provincial coincida con el PDF publicado."""
    q = select(ExtTransferencia.periodo, ExtTransferencia.monto, ExtTransferencia.id_geo).where(
        ExtTransferencia.concepto.in_(conceptos),
        ExtTransferencia.periodo >= date(min(anios), 1, 1),
        ExtTransferencia.periodo <= date(max(anios), 12, 31),
    )
    if ids_geo is not None:
        q = q.where(ExtTransferencia.id_geo.in_(ids_geo or {"__ninguno__"}))
    return q


async def _poblacion_por_codigo(db: AsyncSession, locs: list[ExtGobLocalidad]) -> dict[str, int]:
    """Población 2022 del Censo (INDEC) por código; si falta, la de la Vista de Gobierno."""
    codigos = [loc.codigo_indec for loc in locs]
    censo = dict(
        (
            await db.execute(
                select(ExtGeoCenso.codigo_indec, ExtGeoCenso.poblacion_2022).where(
                    ExtGeoCenso.codigo_indec.in_(codigos), ExtGeoCenso.deleted_at.is_(None)
                )
            )
        ).all()
    ) if codigos else {}
    return {loc.codigo_indec: censo.get(loc.codigo_indec) or loc.poblacion_2022_gob or 0 for loc in locs}


# ── Inicio ──────────────────────────────────────────────────────────────────────


async def get_inicio(db: AsyncSession, anio: int, codigos: list[str] | None) -> InicioResponse:
    locs = await _nomenclador(db, codigos)
    poblacion = await _poblacion_por_codigo(db, locs)
    ids_geo = {loc.id_geo for loc in locs if loc.id_geo} if codigos else None

    filas = (await db.execute(_transferencias_filtradas(CONCEPTOS_SUMABLES, ids_geo, (anio,)))).all()
    serie = aggregations.serie_mensual(((f.periodo, f.monto) for f in filas), anio)
    mes = aggregations.ultimo_mes_con_dato(serie)
    transferido = aggregations.acumulado(serie, mes)

    # Por departamento: solo lo vinculado a una localidad del nomenclador.
    depto_de = {loc.id_geo: loc.departamento_gob for loc in locs if loc.id_geo}
    tr_depto: dict[str, float] = {}
    for f in filas:
        d = depto_de.get(f.id_geo)
        if d:
            tr_depto[d] = tr_depto.get(d, 0.0) + float(f.monto)
    deptos: dict[str, list[ExtGobLocalidad]] = {}
    for loc in locs:
        deptos.setdefault(loc.departamento_gob, []).append(loc)
    por_departamento = []
    for d, ls in sorted(deptos.items()):
        pob = sum(poblacion[loc.codigo_indec] for loc in ls)
        monto = tr_depto.get(d, 0.0)
        por_departamento.append(
            InicioDepartamento(
                departamento=d, localidades=len(ls), poblacion=pob, transferido=monto,
                por_habitante=aggregations.por_habitante(monto, pob),
            )
        )

    pob_total = sum(poblacion.values())
    return InicioResponse(
        anio=anio,
        periodo_hasta=date(anio, mes + 1, 1) if mes is not None else None,
        kpis=InicioKpis(
            localidades=len(locs),
            municipios=sum(1 for loc in locs if loc.tipo == "MU"),
            comunas=sum(1 for loc in locs if loc.tipo == "CO"),
            poblacion=pob_total,
            transferido=transferido,
            por_habitante=aggregations.por_habitante(transferido, pob_total),
        ),
        por_departamento=por_departamento,
        gestion=await gestion.get_inicio_gestion(db, codigos),
    )


# ── Transferencias automáticas (Coparticipación, FOFINDES) ─────────────────────
# Etapa 1: desde el scraping de Transparencia (montos brutos mensuales). La planilla de
# Gobierno (quincenas, neto, retenciones, % a sueldos) llega en la Etapa 2.

CONCEPTOS_SUMABLES = ["coparticipacion_ley_8663", "fasamu", "fofindes", "fondo_compensacion", "bono_consenso_fiscal"]
ETIQUETA_CONCEPTO = {
    "coparticipacion_ley_8663": "Coparticipación (Ley 8663)",
    "fasamu": "FASAMU",
    "fofindes": "FOFINDES",
    "fondo_compensacion": "Fondo de Compensación",
    "bono_consenso_fiscal": "Bono Consenso Fiscal",
}
SECCIONES_TRANSFERENCIAS = {
    "coparticipacion": ("Coparticipación", ["coparticipacion_ley_8663"]),
    "fofindes": ("FOFINDES", ["fofindes"]),
}


async def get_transferencias(
    db: AsyncSession, seccion: str, anio: int, codigos: list[str] | None
) -> TransferenciasResponse:
    etiqueta, conceptos = SECCIONES_TRANSFERENCIAS[seccion]
    ids_geo = {loc.id_geo for loc in await _nomenclador(db, codigos) if loc.id_geo} if codigos else None

    filas_c = (await db.execute(_transferencias_filtradas(conceptos, ids_geo, (anio - 1, anio)))).all()
    serie = aggregations.serie_mensual(((f.periodo, f.monto) for f in filas_c), anio)
    serie_ant = aggregations.serie_mensual(((f.periodo, f.monto) for f in filas_c), anio - 1)
    mes = aggregations.ultimo_mes_con_dato(serie)
    total = aggregations.acumulado(serie, mes)
    acum_ant = aggregations.acumulado(serie_ant, mes) if mes is not None else None

    por_concepto_q = (
        select(ExtTransferencia.concepto, func.sum(ExtTransferencia.monto))
        .where(
            ExtTransferencia.concepto.in_(CONCEPTOS_SUMABLES),
            ExtTransferencia.periodo >= date(anio, 1, 1),
            ExtTransferencia.periodo <= date(anio, 12, 31),
        )
        .group_by(ExtTransferencia.concepto)
    )
    if ids_geo is not None:
        por_concepto_q = por_concepto_q.where(ExtTransferencia.id_geo.in_(ids_geo or {"__ninguno__"}))
    por_concepto = sorted(
        (
            ConceptoMonto(concepto=c, etiqueta=ETIQUETA_CONCEPTO.get(c, c), monto=float(m or 0))
            for c, m in (await db.execute(por_concepto_q)).all()
        ),
        key=lambda x: -x.monto,
    )

    base = TransferenciasResponse(
        concepto=seccion,
        etiqueta=etiqueta,
        anio=anio,
        ultimo_periodo=date(anio, mes + 1, 1) if mes is not None else None,
        total_anio=total,
        acumulado_anterior=acum_ant or None,
        variacion=aggregations.variacion(total, acum_ant),
        ultimo_mes=serie[mes] if mes is not None else None,
        mensual=serie,
        mensual_anterior=serie_ant,
        por_concepto=por_concepto,
        localidades=len({f.id_geo for f in filas_c if f.id_geo and f.periodo.year == anio}),
    )
    # Etapa 2: la planilla de Gobierno manda cuando tiene el año (spec Fase 2 §5).
    return await planillas.enriquecer_transferencias(db, seccion, anio, codigos, base)


# ── Etapa 2: secciones que salen solo de las planillas de Gobierno ───────────────────

# Etapa 3 (spec-datos-externos-fase3-fondos.md §4): los fondos usan la misma ruta para no
# cambiar el gateway.
SECCIONES_PLANILLAS = ("fodemeep", "fommep", "resumen", "fondo-permanente", "fondo-ambiental", "comunidades-regionales")


async def get_seccion_planilla(db: AsyncSession, seccion: str, anio: int, codigos: list[str] | None):
    if seccion == "fondo-permanente":
        return await fondos.get_fondo_permanente(db, codigos)
    if seccion == "fondo-ambiental":
        return await fondos.get_fondo_ambiental(db, codigos)
    if seccion == "comunidades-regionales":
        return await fondos.get_comunidades_regionales(db, codigos)
    if seccion == "fodemeep":
        return await planillas.get_fodemeep(db, anio, codigos)
    if seccion == "fommep":
        return await planillas.get_fommep(db, codigos)
    poblacion = await _poblacion_por_codigo(db, await _nomenclador(db, codigos))
    # Fase 4 (spec-atp-interno.md §4.3): ATP Interno desde svc-gralgob; None si no responde.
    return await planillas.get_resumen(db, anio, codigos, poblacion, await atp_interno.atp_por_localidad(anio))
