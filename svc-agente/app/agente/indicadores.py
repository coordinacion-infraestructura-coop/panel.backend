"""Indicadores prediseñados (spec §5) y resolución de territorio.

Cada función lee de `ag_*` y devuelve un dict serializable a JSON con `datos` (lo que lee el
modelo) y `bloques` (lo que se muestra en el chat: kpi, tabla, link). La agregación es en Python
sobre filas ya filtradas por territorio: los volúmenes son de miles de filas y así el mismo código
corre en Postgres y en los tests con SQLite.
"""
import difflib
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.semantica.glosario import glosario, normalizar, normalizar_departamento
from app.semantica.models import (
    AgAlias, AgAtpPago, AgFrescura, AgGestion, AgHito, AgLocalidad, AgMovimiento,
    AgProgramaItem, AgTransferencia,
)

PROVINCIA = {"tipo": "provincia", "nombre": "Provincia de Córdoba"}
_PALABRAS_PROVINCIA = {"provincia", "toda la provincia", "la provincia", "cordoba provincia",
                       "provincia de cordoba", "total provincial", ""}

FUENTE_POR_PROGRAMA = {
    "cc": "vivienda", "ch": "vivienda", "ml": "vivienda", "gas_obra": "gasifera",
    "gas_accion": "gasifera", "atp": "gralgob", "privada": "privada",
    "transferencias": "datos_externos",
}
NOMBRE_FUENTE = {
    "vivienda": "Vivienda", "privada": "Privada", "gasifera": "Gasífera",
    "gralgob": "Gobierno (ATP)", "datos_externos": "Datos externos",
}


def _r(x: float | None, n: int = 2) -> float | None:
    return None if x is None else round(x, n)


def _hoy() -> date:
    return date.today()


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (date, datetime)) else v


# ── Territorio ────────────────────────────────────────────────────────────────

async def resolver_territorio(db: AsyncSession, texto: str) -> dict:
    """Devuelve {"tipo": provincia|departamento|localidad, ...} o {"tipo": "ambiguo",
    "candidatos": [...]} o {"tipo": "sin_resultado"}. Nunca adivina entre homónimas."""
    t = normalizar(texto)
    t = t.removeprefix("departamento ").removeprefix("depto. ").removeprefix("depto ")
    if t in _PALABRAS_PROVINCIA:
        return dict(PROVINCIA)

    locs = (await db.execute(select(AgLocalidad))).scalars().all()
    deptos = sorted({l.departamento for l in locs})
    por_dep = {normalizar_departamento(d): d for d in deptos}
    if normalizar_departamento(t) in por_dep and "localidad" not in normalizar(texto):
        dep = por_dep[normalizar_departamento(t)]
        homonima = [l for l in locs if normalizar(l.localidad) == t]
        res = {"tipo": "departamento", "departamento": dep}
        if homonima:
            res["aviso"] = (f"También existe la localidad {homonima[0].localidad} "
                            f"({homonima[0].departamento}); si se refería a ella, pedir aclaración.")
        return res

    por_id = {l.id_geo: l for l in locs}
    alias = (await db.execute(select(AgAlias).where(AgAlias.texto_normalizado == t))).scalars().all()
    for a in alias:
        if a.id_geo and a.id_geo in por_id:
            return _loc(por_id[a.id_geo])

    exactas = [l for l in locs if normalizar(l.localidad) == t]
    if len(exactas) == 1:
        return _loc(exactas[0])
    if len(exactas) > 1:
        return {"tipo": "ambiguo", "candidatos": [_loc(l) for l in exactas]}

    nombres = {normalizar(l.localidad): l for l in locs}
    cerca_loc = difflib.get_close_matches(t, list(nombres), n=5, cutoff=0.8)
    cerca_dep = difflib.get_close_matches(normalizar_departamento(t), list(por_dep), n=3, cutoff=0.8)
    candidatos = [{"tipo": "departamento", "departamento": por_dep[d]} for d in cerca_dep]
    candidatos += [_loc(nombres[n]) for n in cerca_loc]
    if len(candidatos) == 1:
        return {**candidatos[0], "aviso": f"Interpreté '{texto}' como el nombre más parecido."}
    if candidatos:
        return {"tipo": "ambiguo", "candidatos": candidatos}
    return {"tipo": "sin_resultado", "texto": texto}


def _loc(l: AgLocalidad) -> dict:
    return {"tipo": "localidad", "id_geo": l.id_geo, "localidad": l.localidad, "departamento": l.departamento}


def _filtros(modelo, departamento: str | None, id_geo: str | None) -> list:
    if id_geo:
        return [modelo.id_geo == id_geo]
    if departamento:
        return [modelo.departamento == departamento]
    return []


def _nombre_territorio(departamento: str | None, id_geo: str | None, loc: AgLocalidad | None) -> str:
    if loc:
        return f"{loc.localidad} (depto. {loc.departamento})"
    if departamento:
        return f"departamento {departamento}"
    return "toda la provincia"


async def contexto_localidad(db: AsyncSession, id_geo: str) -> dict | None:
    """Contexto fijo de spec §5.2."""
    l = await db.get(AgLocalidad, id_geo)
    if not l:
        return None
    return {
        "localidad": l.localidad, "departamento": l.departamento, "poblacion": l.poblacion,
        "intendente": l.intendente, "partido": l.partido, "url_ficha": l.url_ficha,
    }


async def frescura(db: AsyncSession, fuentes: set[str] | None = None) -> list[dict]:
    rows = (await db.execute(select(AgFrescura))).scalars().all()
    return [
        {"fuente": NOMBRE_FUENTE.get(r.fuente, r.fuente), "estado": r.estado,
         "actualizado": _iso(r.ultimo_dato), "refrescado": _iso(r.refrescado_at)}
        for r in rows if fuentes is None or r.fuente in fuentes
    ]


def _link_ficha(loc: AgLocalidad | None) -> list[dict]:
    if not loc or not loc.url_ficha:
        return []
    return [{"tipo": "link", "texto": f"Ficha de {loc.localidad}", "url": loc.url_ficha}]


# ── 1. Estado de programa en territorio ───────────────────────────────────────

async def estado_programa_territorio(
    db: AsyncSession, programa: str | None = None, departamento: str | None = None,
    id_geo: str | None = None,
) -> dict:
    q = select(AgProgramaItem).where(*_filtros(AgProgramaItem, departamento, id_geo))
    if programa:
        q = q.where(AgProgramaItem.programa == programa)
    items = (await db.execute(q)).scalars().all()
    loc = await db.get(AgLocalidad, id_geo) if id_geo else None
    escala = glosario()["estados_normalizados"]

    por_prog: dict[str, list[AgProgramaItem]] = defaultdict(list)
    for it in items:
        por_prog[it.programa].append(it)

    resumen, filas_tabla = [], []
    for prog, lista in sorted(por_prog.items()):
        unicos = {it.origen_id: it for it in lista}
        por_estado = Counter(it.estado_normalizado for it in unicos.values())
        por_origen = Counter(it.estado_origen or "Sin estado" for it in unicos.values())
        total = len(unicos)
        monto = sum(it.monto or 0 for it in lista)
        usd = sum(it.monto_usd or 0 for it in lista)
        fin = por_estado.get("Finalizado", 0)
        r = {
            "programa": prog, "programa_nombre": lista[0].programa_nombre, "total": total,
            "por_estado_normalizado": {e: por_estado.get(e, 0) for e in escala},
            "por_estado_origen": dict(por_origen.most_common()),
            "monto_total_pesos": _r(monto), "monto_total_usd": _r(usd) if usd else None,
            "pct_finalizado": _r(100 * fin / total, 1) if total else None,
            "cantidad_total": sum(it.cantidad or 0 for it in unicos.values()) or None,
        }
        resumen.append(r)
        filas_tabla.append([r["programa_nombre"], total] + [r["por_estado_normalizado"][e] for e in escala]
                           + [r["monto_total_pesos"]])

    mq = select(AgMovimiento).where(*_filtros(AgMovimiento, None, id_geo))
    if programa:
        mq = mq.where(AgMovimiento.programa == programa)
    if departamento and not id_geo:
        ids_geo = {it.id_geo for it in items if it.id_geo}
        mq = mq.where(AgMovimiento.id_geo.in_(ids_geo or {"-"}))
    movs = (await db.execute(mq.order_by(AgMovimiento.fecha.desc()).limit(5))).scalars().all()
    nombre_item = {(it.programa, it.origen_id): it.nombre for it in items}
    ultimos = [
        {"fecha": _iso(m.fecha), "programa": m.programa, "nombre": nombre_item.get((m.programa, m.origen_id)),
         "dimension": m.dimension, "de": m.estado_anterior, "a": m.estado_nuevo}
        for m in movs
    ]

    fuentes = {FUENTE_POR_PROGRAMA[p] for p in por_prog} or {"vivienda"}
    bloques = []
    if resumen:
        bloques.append({
            "tipo": "tabla", "titulo": f"Estado por programa — {_nombre_territorio(departamento, id_geo, loc)}",
            "columnas": ["Programa", "Total"] + escala + ["Monto ($)"], "filas": filas_tabla,
            "total_filas": len(filas_tabla),
        })
    if ultimos:
        bloques.append({
            "tipo": "tabla", "titulo": "Últimos movimientos",
            "columnas": ["Fecha", "Programa", "Nombre", "Dimensión", "De", "A"],
            "filas": [[u["fecha"], u["programa"], u["nombre"], u["dimension"], u["de"], u["a"]] for u in ultimos],
            "total_filas": len(ultimos),
        })
    bloques += _link_ficha(loc)
    return {
        "territorio": _nombre_territorio(departamento, id_geo, loc),
        "contexto_localidad": await contexto_localidad(db, id_geo) if id_geo else None,
        "programas": resumen, "ultimos_movimientos": ultimos,
        "fuentes": await frescura(db, fuentes), "bloques": bloques,
    }


# ── 2. Ficha de localidad / departamento ──────────────────────────────────────

async def ficha_territorio(db: AsyncSession, departamento: str | None = None, id_geo: str | None = None) -> dict:
    if not departamento and not id_geo:
        return {"error": "La ficha necesita una localidad (id_geo) o un departamento."}
    estado = await estado_programa_territorio(db, None, departamento, id_geo)
    loc = await db.get(AgLocalidad, id_geo) if id_geo else None
    hoy = _hoy()
    hace_un_anio = hoy - timedelta(days=365)

    if id_geo:
        contexto = estado["contexto_localidad"]
    else:
        locs = (await db.execute(select(AgLocalidad).where(AgLocalidad.departamento == departamento))).scalars().all()
        contexto = {"departamento": departamento, "localidades": len(locs),
                    "poblacion": sum(l.poblacion or 0 for l in locs) or None}

    gest = (await db.execute(select(AgGestion).where(*_filtros(AgGestion, departamento, id_geo)))).scalars().all()
    gest_por_estado = dict(Counter(g.estado for g in gest).most_common())
    abiertas = [g for g in gest if g.dias_abierta is not None]

    trans = (await db.execute(
        select(AgTransferencia).where(*_filtros(AgTransferencia, departamento, id_geo),
                                      AgTransferencia.periodo >= hace_un_anio)
    )).scalars().all()
    trans_concepto: dict[str, float] = defaultdict(float)
    for t in trans:
        trans_concepto[t.concepto] += t.monto

    atp_items = [p for p in estado["programas"] if p["programa"] == "atp"]
    atp_comp = (await db.execute(
        select(AgProgramaItem).where(AgProgramaItem.programa == "atp",
                                     *_filtros(AgProgramaItem, departamento, id_geo))
    )).scalars().all()
    interno = (await db.execute(
        select(AgAtpPago).where(AgAtpPago.fuente == "interno", *_filtros(AgAtpPago, departamento, id_geo),
                                AgAtpPago.fecha >= hace_un_anio)
    )).scalars().all()

    atp = {
        "compromisos_gobernador": {
            "compromisos": len(atp_comp),
            "anunciado": _r(sum(c.monto or 0 for c in atp_comp)),
            "entregado": _r(sum(c.monto_ejecutado or 0 for c in atp_comp)),
        } if atp_items else None,
        "atp_interno_ultimo_anio": {"pagos": len(interno), "monto": _r(sum(p.monto for p in interno))} if interno else None,
        "nota": "ATP Compromisos y ATP Interno se informan por separado y no se suman (hay pagos repetidos).",
    }
    bloques = [b for b in estado["bloques"] if b["tipo"] != "link" and b.get("titulo") != "Últimos movimientos"]
    kpis = []
    if contexto and contexto.get("poblacion"):
        kpis.append({"tipo": "kpi", "titulo": "Población (Censo 2022)", "valor": contexto["poblacion"], "unidad": "habitantes"})
    kpis.append({"tipo": "kpi", "titulo": "Gestiones abiertas (Privada)", "valor": len(abiertas), "unidad": "gestiones"})
    if trans:
        kpis.append({"tipo": "kpi", "titulo": "Transferencias últimos 12 meses", "valor": _r(sum(trans_concepto.values())), "unidad": "$"})
    if gest_por_estado:
        bloques.append({"tipo": "tabla", "titulo": "Gestiones de Privada por estado",
                        "columnas": ["Estado", "Gestiones"], "filas": [[k, v] for k, v in gest_por_estado.items()],
                        "total_filas": len(gest_por_estado)})
    return {
        "territorio": estado["territorio"], "contexto": contexto, "programas": estado["programas"],
        "gestiones_privada": {"total": len(gest), "abiertas": len(abiertas), "por_estado": gest_por_estado},
        "transferencias_ultimo_anio": {"total": _r(sum(trans_concepto.values())),
                                       "por_concepto": {k: _r(v) for k, v in sorted(trans_concepto.items())}},
        "atp": atp,
        "fuentes": await frescura(db),
        "bloques": kpis + bloques + _link_ficha(loc),
    }


# ── 3. Montos ─────────────────────────────────────────────────────────────────

async def montos(
    db: AsyncSession, programa: str | None = None, departamento: str | None = None,
    id_geo: str | None = None, desde: str | None = None, hasta: str | None = None,
) -> dict:
    d = date.fromisoformat(desde) if desde else None
    h = date.fromisoformat(hasta) if hasta else None
    q = select(AgProgramaItem).where(*_filtros(AgProgramaItem, departamento, id_geo))
    if programa:
        q = q.where(AgProgramaItem.programa == programa)
    if d:
        q = q.where(AgProgramaItem.fecha_inicio >= d)
    if h:
        q = q.where(AgProgramaItem.fecha_inicio <= h)
    items = (await db.execute(q)).scalars().all()
    loc = await db.get(AgLocalidad, id_geo) if id_geo else None
    defin = glosario()["ejecutado"]

    por_prog: dict[str, list] = defaultdict(list)
    for it in items:
        por_prog[it.programa].append(it)
    filas, datos = [], []
    for prog, lista in sorted(por_prog.items()):
        comp = sum(it.monto or 0 for it in lista)
        ejec_vals = [it.monto_ejecutado for it in lista if it.monto_ejecutado is not None]
        ejec = sum(ejec_vals) if ejec_vals else None
        usd = sum(it.monto_usd or 0 for it in lista)
        r = {
            "programa": prog, "programa_nombre": lista[0].programa_nombre,
            "convenios": len({it.origen_id for it in lista}),
            "comprometido_pesos": _r(comp), "ejecutado_pesos": _r(ejec),
            "ratio_ejecutado_pct": _r(100 * ejec / comp, 1) if ejec is not None and comp else None,
            "monto_usd": _r(usd) if usd else None, "definicion_ejecutado": defin.get(prog),
        }
        datos.append(r)
        filas.append([r["programa_nombre"], r["convenios"], r["comprometido_pesos"], r["ejecutado_pesos"],
                      r["ratio_ejecutado_pct"], r["monto_usd"]])
    if programa in (None, "transferencias"):
        tq = select(AgTransferencia).where(*_filtros(AgTransferencia, departamento, id_geo))
        if d:
            tq = tq.where(AgTransferencia.periodo >= d)
        if h:
            tq = tq.where(AgTransferencia.periodo <= h)
        trans = (await db.execute(tq)).scalars().all()
        if trans:
            total = sum(t.monto for t in trans)
            datos.append({"programa": "transferencias", "programa_nombre": "Transferencias a municipios",
                          "transferido_pesos": _r(total)})
            filas.append(["Transferencias a municipios", None, None, _r(total), None, None])
    bloques = []
    if filas:
        bloques.append({
            "tipo": "tabla", "titulo": f"Montos — {_nombre_territorio(departamento, id_geo, loc)}",
            "columnas": ["Programa", "Convenios", "Comprometido ($)", "Ejecutado ($)", "% ejecutado", "USD"],
            "filas": filas, "total_filas": len(filas),
        })
    return {
        "territorio": _nombre_territorio(departamento, id_geo, loc),
        "periodo": {"desde": desde, "hasta": hasta, "aplica_a": "fecha de inicio/anuncio del convenio; período de la transferencia"},
        "programas": datos,
        "notas": ["Pesos y dólares no se suman.", "ATP Interno no se incluye acá: consultar ag_atp_pagos por separado."],
        "fuentes": await frescura(db), "bloques": bloques + _link_ficha(loc),
    }


# ── 4. Demoras y pendientes ───────────────────────────────────────────────────

async def pendientes(
    db: AsyncSession, tipo: str = "gestiones", umbral_dias: int | None = None,
    departamento: str | None = None, id_geo: str | None = None, programa: str | None = None,
) -> dict:
    umbrales = glosario()["umbrales_demora_dias"]
    loc = await db.get(AgLocalidad, id_geo) if id_geo else None
    terr = _nombre_territorio(departamento, id_geo, loc)

    if tipo == "gestiones":
        umbral = umbral_dias or umbrales["gestiones"]
        q = select(AgGestion).where(AgGestion.dias_abierta.is_not(None), *_filtros(AgGestion, departamento, id_geo))
        abiertas = (await db.execute(q)).scalars().all()
        sobre = [g for g in abiertas if g.dias_abierta > umbral]

        def ranking(attr: str) -> list[dict]:
            grupos: dict[str, list[int]] = defaultdict(list)
            for g in abiertas:
                grupos[getattr(g, attr) or "Sin dato"].append(g.dias_abierta)
            filas = [{"nombre": k, "abiertas": len(v), "sobre_umbral": sum(1 for x in v if x > umbral),
                      "promedio_dias": round(mean(v))} for k, v in grupos.items()]
            return sorted(filas, key=lambda f: (-f["sobre_umbral"], -f["promedio_dias"]))[:10]

        mas_antiguas = sorted(abiertas, key=lambda g: -g.dias_abierta)[:10]
        rank_area = ranking("area")
        return {
            "territorio": terr, "tipo": tipo, "umbral_dias": umbral,
            "abiertas": len(abiertas), "sobre_umbral": len(sobre),
            "antiguedad_promedio_dias": round(mean(g.dias_abierta for g in abiertas)) if abiertas else None,
            "antiguedad_maxima_dias": max((g.dias_abierta for g in abiertas), default=None),
            "ranking_area": rank_area, "ranking_ministerio": ranking("ministerio"),
            "mas_antiguas": [{"fecha_ingreso": _iso(g.fecha_ingreso), "localidad": g.localidad, "area": g.area,
                              "estado": g.estado, "dias": g.dias_abierta, "detalle": (g.detalle or "")[:160]}
                             for g in mas_antiguas],
            "fuentes": await frescura(db, {"privada"}),
            "bloques": [
                {"tipo": "kpi", "titulo": f"Gestiones abiertas hace más de {umbral} días", "valor": len(sobre), "unidad": f"de {len(abiertas)} abiertas"},
                {"tipo": "tabla", "titulo": "Áreas con más demoras", "columnas": ["Área", "Abiertas", f"> {umbral} días", "Promedio (días)"],
                 "filas": [[f["nombre"], f["abiertas"], f["sobre_umbral"], f["promedio_dias"]] for f in rank_area], "total_filas": len(rank_area)},
                {"tipo": "tabla", "titulo": "Gestiones más antiguas", "columnas": ["Ingreso", "Localidad", "Área", "Estado", "Días", "Detalle"],
                 "filas": [[_iso(g.fecha_ingreso), g.localidad, g.area, g.estado, g.dias_abierta, (g.detalle or "")[:80]] for g in mas_antiguas],
                 "total_filas": len(abiertas)},
            ] + _link_ficha(loc),
        }

    if tipo == "programas":
        umbral = umbral_dias or umbrales["programas"]
        abiertos_estados = set(glosario()["estados_abiertos"])
        q = select(AgProgramaItem).where(*_filtros(AgProgramaItem, departamento, id_geo))
        if programa:
            q = q.where(AgProgramaItem.programa == programa)
        items = [it for it in (await db.execute(q)).scalars().all() if it.estado_normalizado in abiertos_estados]
        movs = (await db.execute(select(AgMovimiento))).scalars().all()
        ultimo_mov: dict[tuple[str, str], datetime] = {}
        for m in movs:
            if m.fecha and ((m.programa, m.origen_id) not in ultimo_mov or m.fecha > ultimo_mov[(m.programa, m.origen_id)]):
                ultimo_mov[(m.programa, m.origen_id)] = m.fecha
        hoy = _hoy()
        filas = []
        vistos = set()
        for it in items:
            if (it.programa, it.origen_id) in vistos:
                continue
            vistos.add((it.programa, it.origen_id))
            ref = ultimo_mov.get((it.programa, it.origen_id)) or it.fecha_ultimo_cambio
            dias = (hoy - (ref.date() if isinstance(ref, datetime) else ref)).days if ref else None
            filas.append({"programa": it.programa_nombre, "nombre": it.nombre, "localidad": it.localidad,
                          "estado": it.estado_origen, "estado_normalizado": it.estado_normalizado,
                          "dias_sin_movimiento": dias})
        sobre = sorted([f for f in filas if f["dias_sin_movimiento"] is not None and f["dias_sin_movimiento"] > umbral],
                       key=lambda f: -f["dias_sin_movimiento"])
        por_estado = Counter((f["programa"], f["estado"]) for f in sobre)
        return {
            "territorio": terr, "tipo": tipo, "umbral_dias": umbral, "abiertos": len(filas),
            "sin_movimiento_sobre_umbral": len(sobre),
            "trabados_por_programa_y_estado": [{"programa": p, "estado": e, "cantidad": n} for (p, e), n in por_estado.most_common(15)],
            "detalle": sobre[:15],
            "nota": "Días sin movimiento = desde el último cambio de estado registrado (o la última edición). estado_general de Vivienda no tiene historial.",
            "fuentes": await frescura(db),
            "bloques": [
                {"tipo": "kpi", "titulo": f"Convenios/obras sin movimiento hace más de {umbral} días", "valor": len(sobre), "unidad": f"de {len(filas)} abiertos"},
                {"tipo": "tabla", "titulo": "Sin movimiento", "columnas": ["Programa", "Nombre", "Localidad", "Estado", "Días"],
                 "filas": [[f["programa"], f["nombre"], f["localidad"], f["estado"], f["dias_sin_movimiento"]] for f in sobre[:50]],
                 "total_filas": len(sobre)},
            ] + _link_ficha(loc),
        }

    if tipo == "hitos":
        hq = select(AgHito).where(AgHito.fecha_acreditado.is_(None), AgHito.hito != "100", *_filtros(AgHito, None, id_geo))
        if programa:
            hq = hq.where(AgHito.programa == programa)
        hitos = (await db.execute(hq)).scalars().all()
        if departamento and not id_geo:
            geos = {l.id_geo for l in (await db.execute(select(AgLocalidad).where(AgLocalidad.departamento == departamento))).scalars()}
            hitos = [h for h in hitos if h.id_geo in geos]
        por = defaultdict(lambda: {"hitos": 0, "monto": 0.0})
        for h in hitos:
            por[(h.programa, h.hito)]["hitos"] += 1
            por[(h.programa, h.hito)]["monto"] += h.monto or 0
        filas = [[p, hi, v["hitos"], _r(v["monto"])] for (p, hi), v in sorted(por.items())]
        return {
            "territorio": terr, "tipo": tipo, "hitos_sin_acreditar": len(hitos),
            "monto_pendiente": _r(sum(h.monto or 0 for h in hitos)),
            "por_programa_e_hito": [{"programa": f[0], "hito": f[1], "cantidad": f[2], "monto": f[3]} for f in filas],
            "fuentes": await frescura(db, {"vivienda"}),
            "bloques": [{"tipo": "tabla", "titulo": "Hitos sin acreditar", "columnas": ["Programa", "Hito", "Cantidad", "Monto ($)"],
                         "filas": filas, "total_filas": len(filas)}] + _link_ficha(loc),
        }
    return {"error": f"tipo desconocido: {tipo}. Usar gestiones, programas o hitos."}


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)
