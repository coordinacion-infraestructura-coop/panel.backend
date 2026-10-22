"""Tablero de Gobierno, Etapa 6: Político — padrón de intendentes y elecciones
(spec-datos-externos-fase6-politico.md §3.3 y §4).

Solo `Admin` y `Autoridad` (el router ya lo exige para todo el tablero). Nada de esto sale por el
rollup ni por `resumen_territorial`.

Las pestañas pegadas de la planilla 18 no se muestran tal cual: votos, porcentajes, ganador,
segundo, margen y variación se recalculan desde los votos por circuito, y cada diferencia con lo
pegado se lista en `diferencias` (spec §3.3). Lo que no tiene base (gobernador 2023, alineación del
intendente) sale de la copia. Las funciones `armar_*` son puras para poder testear cada cálculo.
"""
import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_fondos.parse import sin_tildes
from app.gob_politico.models import (
    ExtGobCircuitoLocalidad,
    ExtGobEleccionCircuito,
    ExtGobEleccionCopia,
    ExtGobEleccionMunicipal,
    ExtGobIntendente,
)
from app.gob_politico.parse import ELECCIONES, OTROS
from app.gobierno.models import ExtGobLocalidad
from app.tablero.schemas import (
    Conteo,
    DiferenciaPlanilla,
    EleccionDepartamento,
    EleccionFuerza,
    EleccionLocalidad,
    EleccionResultado,
    EleccionesResponse,
    IntendenteFila,
    IntendentesDepartamento,
    IntendentesKpis,
    IntendentesResponse,
    MunicipalFila,
    MunicipalesResultado,
    VariacionFila,
)

SECCIONES_POLITICO = ("intendentes", "elecciones")
SIN_DATO = "SIN DATO"
# Tolerancia del control contra las pestañas pegadas: 0,05 puntos porcentuales (spec §3.3).
TOLERANCIA = 0.0005

TITULOS = {
    "diputados_2025": "Diputados nacionales 2025",
    "diputados_2023": "Diputados nacionales 2023",
    "diputados_2021": "Diputados nacionales 2021",
    "gobernador_2023": "Gobernador 2023",
}
# Siglas que usa la planilla, por nombre de fuerza sin tildes. Las fuerzas sin sigla se muestran
# con su nombre.
SIGLAS = {
    "ALIANZA LA LIBERTAD AVANZA": "LLA",
    "LA LIBERTAD AVANZA": "LLA",
    "ALIANZA PROVINCIAS UNIDAS": "PU",
    "DEFENDAMOS CORDOBA": "DC",
    "ALIANZA FUERZA PATRIA": "FP",
    "UNION CIVICA RADICAL": "UCR",
    "FRENTE DE IZQUIERDA Y DE TRABAJADORES - UNIDAD": "FIT-U",
    "PARTIDO LIBERTARIO": "PL",
    "PRO - PROPUESTA REPUBLICANA": "PRO",
    "POLITICA ABIERTA PARA LA INTEGRIDAD SOCIAL": "PAIS",
    "HACEMOS POR NUESTRO PAIS": "HxC",
    "HACEMOS POR CORDOBA": "HxC",
    "JUNTOS POR EL CAMBIO": "JxC",
    "UNION POR LA PATRIA": "UxP",
    "FRENTE DE TODOS": "FdT",
    "ENCUENTRO VECINAL CORDOBA": "EV",
    "UNION POPULAR FEDERAL": "UPF",
    OTROS: "Otros",
}
# Columnas que la pestaña `RESULTADOS CALVO` resume por elección; el resto va a "Otros".
_RESUMIDAS = {"diputados_2025": ("LLA", "PU", "DC"), "diputados_2023": ("HxC", "JxC", "LLA"), "diputados_2021": ("HxC", "JxC", "LLA")}
_CLAVE_COPIA = {"diputados_2025": ("d25", "v25", "ganador_25"), "diputados_2023": ("d23", "v23", "ganador_23"),
                "diputados_2021": ("d21", "v21", "ganador_21")}


def sigla(fuerza: str) -> str:
    return SIGLAS.get(sin_tildes(fuerza).upper(), fuerza)


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b else None


# ── Intendentes ────────────────────────────────────────────────────────────────────


def armar_intendentes(
    intendentes: list[ExtGobIntendente], universo: list[ExtGobLocalidad], alineacion: dict[str, str]
) -> IntendentesResponse:
    por_codigo = {i.codigo_indec: i for i in intendentes}
    filas: list[IntendenteFila] = []
    for loc in sorted(universo, key=lambda x: (x.departamento_gob, x.nombre_gob)):
        i = por_codigo.get(loc.codigo_indec)
        filas.append(IntendenteFila(
            codigo_indec=loc.codigo_indec,
            localidad=loc.nombre_gob,
            departamento=loc.departamento_gob,
            tipo=loc.tipo,
            intendente=i.intendente if i else None,
            reelecto=i.reelecto if i else None,
            partido=i.partido if i else None,
            continuidad=i.continuidad if i else None,
            alineacion=alineacion.get(loc.codigo_indec),
            celular=i.celular if i else None,
            foto_url=i.foto_url if i else None,
        ))
    con_dato = [f for f in filas if f.intendente]
    deptos: dict[str, list[IntendenteFila]] = defaultdict(list)
    for f in filas:
        deptos[f.departamento].append(f)
    return IntendentesResponse(
        kpis=IntendentesKpis(
            gobiernos_locales=len(filas),
            con_intendente=len(con_dato),
            reelectos=sum(1 for f in con_dato if f.reelecto),
            continuidad=sum(1 for f in con_dato if f.continuidad),
            con_celular=sum(1 for f in con_dato if f.celular),
        ),
        por_partido=[Conteo(clave=k, cantidad=n) for k, n in Counter(f.partido or SIN_DATO for f in con_dato).most_common()],
        por_alineacion=[Conteo(clave=k, cantidad=n) for k, n in Counter(f.alineacion or SIN_DATO for f in con_dato).most_common()],
        por_departamento=[
            IntendentesDepartamento(
                departamento=d,
                total=len(fs),
                por_alineacion=dict(Counter(f.alineacion or SIN_DATO for f in fs if f.intendente)),
                por_partido=dict(Counter(f.partido or SIN_DATO for f in fs if f.intendente)),
            )
            for d, fs in sorted(deptos.items())
        ],
        intendentes=filas,
    )


# ── Elecciones ─────────────────────────────────────────────────────────────────────


class _Totales:
    """Votos sumados de un conjunto de circuitos."""

    def __init__(self) -> None:
        self.padron = 0
        self.tiene_padron = False
        self.total_votos = 0
        self.afirmativos = 0
        self.votos: Counter = Counter()

    def sumar(self, c: ExtGobEleccionCircuito) -> None:
        if c.padron is not None:
            self.padron += c.padron
            self.tiene_padron = True
        self.total_votos += c.total_votos or 0
        self.afirmativos += c.afirmativos or 0
        for f, v in (c.votos or {}).items():
            self.votos[sigla(f)] += v or 0

    def pct(self) -> dict[str, float]:
        return {f: v / self.afirmativos for f, v in self.votos.items()} if self.afirmativos else {}

    def podio(self) -> tuple[str | None, float | None, str | None, float | None]:
        """Ganador y segundo sobre todas las fuerzas, sin "Otros" (spec §3.3 punto 4)."""
        p = self.pct()
        orden = sorted((f for f in p if f != SIGLAS[OTROS]), key=lambda f: -p[f])
        g = orden[0] if orden else None
        s = orden[1] if len(orden) > 1 else None
        return g, p.get(g) if g else None, s, p.get(s) if s else None

    def participacion(self) -> float | None:
        return _ratio(self.total_votos, self.padron) if self.tiene_padron else None


def _localidad_fila(codigo: str, loc: ExtGobLocalidad | None, t: _Totales, principales: list[str]) -> EleccionLocalidad:
    g, gp, s, sp = t.podio()
    p = t.pct()
    resto = 1 - sum(p.get(f, 0) for f in principales) if p else None
    return EleccionLocalidad(
        codigo_indec=codigo,
        localidad=loc.nombre_gob if loc else codigo,
        departamento=loc.departamento_gob if loc else None,
        padron=t.padron if t.tiene_padron else None,
        afirmativos=t.afirmativos,
        participacion=t.participacion(),
        ganador=g, ganador_pct=gp, segundo=s, segundo_pct=sp,
        margen=gp - sp if gp is not None and sp is not None else None,
        pct={**{f: p.get(f, 0.0) for f in principales}, "Otras": resto} if p else {},
    )


def armar_eleccion(
    eleccion: str,
    circuitos: list[ExtGobEleccionCircuito],
    codigo_de: dict[str, str],
    universo: dict[str, ExtGobLocalidad],
    codigos: set[str] | None,
) -> tuple[EleccionResultado, dict[str, _Totales]]:
    provincia = _Totales()
    por_loc: dict[str, _Totales] = defaultdict(_Totales)
    por_depto: dict[str, _Totales] = defaultdict(_Totales)
    for c in circuitos:
        codigo = codigo_de.get(c.circuito_id)
        if codigos is not None and codigo not in codigos:
            continue
        provincia.sumar(c)
        por_depto[c.departamento or SIN_DATO].sumar(c)
        if codigo:
            por_loc[codigo].sumar(c)
    pct = provincia.pct()
    fuerzas = sorted(provincia.votos, key=lambda f: (f == SIGLAS[OTROS], -provincia.votos[f]))
    principales = [f for f in fuerzas if f != SIGLAS[OTROS]][:4]
    deptos = []
    for d, t in sorted(por_depto.items()):
        g, gp, s, sp = t.podio()
        deptos.append(EleccionDepartamento(
            departamento=d, padron=t.padron if t.tiene_padron else None, afirmativos=t.afirmativos,
            participacion=t.participacion(), ganador=g, ganador_pct=gp, segundo=s, segundo_pct=sp,
            margen=gp - sp if gp is not None and sp is not None else None,
        ))
    locs = sorted(
        (_localidad_fila(c, universo.get(c), t, principales) for c, t in por_loc.items()),
        key=lambda f: (f.departamento or "", f.localidad),
    )
    return EleccionResultado(
        eleccion=eleccion,
        titulo=TITULOS[eleccion],
        fuente="circuitos",
        padron=provincia.padron if provincia.tiene_padron else None,
        total_votos=provincia.total_votos,
        afirmativos=provincia.afirmativos,
        participacion=provincia.participacion(),
        principales=principales,
        fuerzas=[EleccionFuerza(fuerza=f, votos=provincia.votos[f], pct=pct.get(f)) for f in fuerzas],
        localidades_ganadas=[Conteo(clave=k, cantidad=n) for k, n in Counter(f.ganador for f in locs if f.ganador).most_common()],
        por_departamento=deptos,
        por_localidad=locs,
    ), por_loc


def armar_gobernador(copias: list[ExtGobEleccionCopia], universo: dict[str, ExtGobLocalidad], codigos: set[str] | None) -> EleccionResultado:
    """Gobernador 2023: solo hay porcentajes por localidad, pegados (spec §3.3 punto 3). Sin
    votos no hay total provincial ni por departamento."""
    locs = []
    principales = ["HxC", "JxC", "LLA", "FdT"]
    for c in copias:
        if not c.codigo_indec or (codigos is not None and c.codigo_indec not in codigos):
            continue
        p = {k: _num(v) for k, v in (c.datos.get("gob23") or {}).items()}
        validos = {k: v for k, v in p.items() if v is not None and k != OTROS}
        orden = sorted(validos, key=lambda k: -validos[k])
        g, s = (orden + [None, None])[:2]
        loc = universo.get(c.codigo_indec)
        locs.append(EleccionLocalidad(
            codigo_indec=c.codigo_indec,
            localidad=loc.nombre_gob if loc else c.localidad,
            departamento=loc.departamento_gob if loc else None,
            ganador=g, ganador_pct=validos.get(g) if g else None, segundo=s, segundo_pct=validos.get(s) if s else None,
            margen=validos[g] - validos[s] if g and s else None,
            pct={**{k: p.get(k) for k in principales}, "Otras": p.get(OTROS)},
        ))
    locs.sort(key=lambda f: (f.departamento or "", f.localidad))
    return EleccionResultado(
        eleccion="gobernador_2023", titulo=TITULOS["gobernador_2023"], fuente="copia", principales=principales,
        localidades_ganadas=[Conteo(clave=k, cantidad=n) for k, n in Counter(f.ganador for f in locs if f.ganador).most_common()],
        por_localidad=locs,
    )


def armar_municipales(filas: list[ExtGobEleccionMunicipal], universo: dict[str, ExtGobLocalidad], codigos: set[str] | None) -> MunicipalesResultado:
    out = []
    for m in filas:
        if codigos is not None and m.codigo_indec not in codigos:
            continue
        loc = universo.get(m.codigo_indec)
        out.append(MunicipalFila(
            codigo_indec=m.codigo_indec,
            localidad=loc.nombre_gob if loc else m.codigo_indec,
            departamento=loc.departamento_gob if loc else None,
            tipo_gobierno=m.tipo_gobierno,
            fecha=m.fecha,
            periodo=m.periodo,
            participacion=m.participacion,
            padron=m.padron,
            afirmativos=m.afirmativos,
            ganador_partido=m.ganador_partido_norm or m.ganador_partido,
            ganador_lista=m.ganador_partido,
            ganador_nombre=m.ganador_nombre,
            ganador_pct=m.ganador_pct,
            segundo_partido=m.segundo_partido_norm or m.segundo_partido,
            segundo_nombre=m.segundo_nombre,
            segundo_pct=m.segundo_pct,
            margen=m.ganador_pct - m.segundo_pct if m.ganador_pct is not None and m.segundo_pct is not None else None,
        ))
    out.sort(key=lambda f: (f.departamento or "", f.localidad))
    return MunicipalesResultado(
        localidades_ganadas=[Conteo(clave=k, cantidad=n) for k, n in Counter(f.ganador_partido or SIN_DATO for f in out).most_common()],
        sin_votos=sum(1 for f in out if f.afirmativos is None),
        por_localidad=out,
    )


def armar_variacion(t23: dict[str, _Totales], t25: dict[str, _Totales], universo: dict[str, ExtGobLocalidad]) -> list[VariacionFila]:
    """LLA 2023 → 2025 y Provincias Unidas 2025 contra Hacemos 2023, como la pestaña `VARIACION`."""
    filas = []
    for codigo in sorted(set(t23) & set(t25)):
        p23, p25 = t23[codigo].pct(), t25[codigo].pct()
        if not p23 or not p25:
            continue
        loc = universo.get(codigo)
        lla23, lla25, hxc23, pu25 = p23.get("LLA", 0.0), p25.get("LLA", 0.0), p23.get("HxC", 0.0), p25.get("PU", 0.0)
        filas.append(VariacionFila(
            codigo_indec=codigo, localidad=loc.nombre_gob if loc else codigo, departamento=loc.departamento_gob if loc else None,
            lla_2023=lla23, lla_2025=lla25, variacion_lla=lla25 - lla23, hxc_2023=hxc23, pu_2025=pu25, variacion_pu_hxc=pu25 - hxc23,
        ))
    return sorted(filas, key=lambda f: (f.departamento or "", f.localidad))


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and abs(v) <= 1.5 and not v.is_integer():
        return f"{v * 100:.2f} %"
    if isinstance(v, (int, float)):
        return f"{int(round(v)):,}".replace(",", ".")
    return str(v)


def armar_diferencias(
    copias: list[ExtGobEleccionCopia], totales: dict[str, dict[str, _Totales]], universo: dict[str, ExtGobLocalidad]
) -> list[DiferenciaPlanilla]:
    """Compara las pestañas pegadas contra el recálculo (spec §3.3 punto 2)."""
    out: list[DiferenciaPlanilla] = []

    def nombre(c: ExtGobEleccionCopia) -> str:
        loc = universo.get(c.codigo_indec or "")
        return loc.nombre_gob if loc else c.localidad

    def agregar(c: ExtGobEleccionCopia, campo: str, planilla: Any, calculado: Any) -> None:
        out.append(DiferenciaPlanilla(localidad=nombre(c), pestana=c.pestana, campo=campo, planilla=_fmt(planilla), calculado=_fmt(calculado)))

    def comparar_pct(c, campo, planilla, calculado):
        p = _num(planilla)
        if calculado is not None and (p is None or abs(p - calculado) > TOLERANCIA):
            agregar(c, campo, planilla, calculado)

    def comparar_votos(c, campo, planilla, calculado):
        if calculado is not None and _num(planilla) != calculado:
            agregar(c, campo, planilla, calculado)

    for c in copias:
        if not c.codigo_indec:
            continue
        d = c.datos or {}
        for eleccion, (k_pct, k_votos, k_gan) in _CLAVE_COPIA.items():
            t = totales.get(eleccion, {}).get(c.codigo_indec)
            if t is None or not t.afirmativos:
                continue
            titulo = TITULOS[eleccion]
            p = t.pct()
            resumidas = _RESUMIDAS[eleccion]
            otras = 1 - sum(p.get(f, 0) for f in resumidas)
            g, gp, s, sp = t.podio()
            if c.pestana == "RESULTADOS CALVO":
                for f in resumidas:
                    comparar_pct(c, f"{titulo} · % {f}", d.get(k_pct, {}).get(f), p.get(f, 0.0))
                comparar_pct(c, f"{titulo} · % Otros", d.get(k_pct, {}).get(OTROS), otras)
                if eleccion == "diputados_2025":
                    if (d.get("ganador_25") or "").upper() != (g or "").upper():
                        agregar(c, f"{titulo} · ganador", d.get("ganador_25"), g)
                    if (d.get("segundo_25") or "").upper() != (s or "").upper():
                        agregar(c, f"{titulo} · segundo", d.get("segundo_25"), s)
                    if gp is not None and sp is not None:
                        comparar_pct(c, f"{titulo} · margen ganador–segundo", d.get("dif_ganador_segundo_25"), gp - sp)
                    if t.tiene_padron:
                        comparar_votos(c, "Padrón 2025", d.get("padron"), t.padron)
            elif c.pestana == "RESUMEN_VOTOS":
                v = d.get(k_votos, {})
                comparar_votos(c, f"{titulo} · afirmativos", v.get("AFIRMATIVOS"), t.afirmativos)
                for f in resumidas:
                    comparar_votos(c, f"{titulo} · votos {f}", v.get(f), t.votos.get(f, 0))
                comparar_votos(c, f"{titulo} · votos Otros", v.get(OTROS), t.afirmativos - sum(t.votos.get(f, 0) for f in resumidas))
                if eleccion == "diputados_2025" and t.tiene_padron:
                    comparar_votos(c, "Padrón 2025", d.get("padron"), t.padron)
            elif c.pestana == "GANADORES":
                if (d.get(k_gan) or "").upper() != (g or "").upper():
                    agregar(c, f"{titulo} · ganador", d.get(k_gan), g)
        if c.pestana == "RESULTADOS CALVO":
            gob = [_num(v) for v in (d.get("gob23") or {}).values()]
            if gob and all(v is not None for v in gob) and abs(sum(gob) - 1) > 0.01:
                agregar(c, "Gobernador 2023 · suma de porcentajes", sum(gob), 1.0)
    return sorted(out, key=lambda x: (x.pestana, x.localidad, x.campo))


# ── Lectura ────────────────────────────────────────────────────────────────────────


async def _universo(db: AsyncSession) -> dict[str, ExtGobLocalidad]:
    q = select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None))
    return {loc.codigo_indec: loc for loc in (await db.execute(q)).scalars()}


async def get_intendentes(db: AsyncSession, codigos: list[str] | None) -> IntendentesResponse:
    universo = await _universo(db)
    elegidos = [loc for c, loc in universo.items() if not codigos or c in codigos]
    intendentes = list((await db.execute(select(ExtGobIntendente))).scalars())
    # La planilla numera las categorías para ordenarlas (`1.PURO`): se quita el número.
    alineacion = {
        c.codigo_indec: re.sub(r"^\d+\.\s*", "", c.datos.get("alineacion"))
        for c in (await db.execute(select(ExtGobEleccionCopia).where(ExtGobEleccionCopia.pestana == "GANADORES"))).scalars()
        if c.codigo_indec and c.datos.get("alineacion")
    }
    return armar_intendentes(intendentes, elegidos, alineacion)


async def get_elecciones(db: AsyncSession, codigos: list[str] | None) -> EleccionesResponse:
    universo = await _universo(db)
    filtro = set(codigos) if codigos else None
    codigo_de = {c.circuito_id: c.codigo_indec for c in (await db.execute(select(ExtGobCircuitoLocalidad))).scalars() if c.codigo_indec}
    resultados: list[EleccionResultado] = []
    totales: dict[str, dict[str, _Totales]] = {}
    circuitos_sin_localidad = 0
    for eleccion in ELECCIONES.values():
        circuitos = list((await db.execute(select(ExtGobEleccionCircuito).where(ExtGobEleccionCircuito.eleccion == eleccion))).scalars())
        if not circuitos:
            continue
        circuitos_sin_localidad = max(circuitos_sin_localidad, sum(1 for c in circuitos if c.circuito_id not in codigo_de))
        r, por_loc = armar_eleccion(eleccion, circuitos, codigo_de, universo, filtro)
        resultados.append(r)
        totales[eleccion] = por_loc
    copias = list((await db.execute(select(ExtGobEleccionCopia))).scalars())
    calvo = [c for c in copias if c.pestana == "RESULTADOS CALVO"]
    if calvo:
        resultados.insert(1 if resultados else 0, armar_gobernador(calvo, universo, filtro))
    municipales = list((await db.execute(select(ExtGobEleccionMunicipal))).scalars())
    elegidas = [c for c in copias if filtro is None or c.codigo_indec in filtro]
    return EleccionesResponse(
        elecciones=resultados,
        municipales=armar_municipales(municipales, universo, filtro) if municipales else None,
        variacion=armar_variacion(totales.get("diputados_2023", {}), totales.get("diputados_2025", {}), universo),
        diferencias=armar_diferencias(elegidas, totales, universo),
        circuitos_sin_localidad=circuitos_sin_localidad,
    )


async def get_seccion(db: AsyncSession, seccion: str, codigos: list[str] | None):
    if seccion == "intendentes":
        return await get_intendentes(db, codigos)
    return await get_elecciones(db, codigos)
