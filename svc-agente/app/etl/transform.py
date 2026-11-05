"""Transformación pura (sin DB) de filas crudas de las fuentes a filas de `ag_*` (spec §3).

Testeable sin Postgres: recibe listas de dicts (lo que devuelven los extractores) y devuelve
listas de dicts con las columnas de `app.semantica.models`.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from app.semantica.glosario import enmascarar, estado_normalizado, programa_info, url_ficha

Fila = dict[str, Any]

# Mismo cálculo que svc-vivienda `checklist_tecnico/catalog.monto_hito` (spec §5.5 del checklist).
HITOS_PORCENTAJE = {"anticipo": 0.5, "40": 0.25, "70": 0.25, "100": 0.0}

CAMPO_DIMENSION = {"ejuridico": "juridico", "efinanciero": "financiero", "etecnico": "tecnico"}


def _f(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _fecha(v: Any) -> date | None:
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v)[:10])


def _dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return datetime.fromisoformat(str(v))


class Padron:
    """id_geo -> (departamento, localidad) oficiales, para completar filas de otras fuentes."""

    def __init__(self, localidades: Iterable[Fila]):
        self._por_id = {l["id_geo"]: l for l in localidades}

    def oficial(self, id_geo: str | None, dep: str | None, loc: str | None) -> tuple[str | None, str | None]:
        l = self._por_id.get(id_geo) if id_geo else None
        if l:
            return l["departamento"], l["localidad"]
        return dep, loc

    def __contains__(self, id_geo: str | None) -> bool:
        return bool(id_geo) and id_geo in self._por_id


# ── Localidades ───────────────────────────────────────────────────────────────

def localidades(
    padron_rows: list[Fila],
    censo_rows: list[Fila] | None,
    politico_rows: list[Fila] | None,
    previas: dict[str, Fila],
) -> list[Fila]:
    """Si censo o padrón político no se pudieron leer en esta corrida, se conservan los valores
    del refresco anterior (`previas`) en vez de borrarlos."""
    censo = {c["id_geo"]: c for c in censo_rows or [] if c.get("id_geo")}
    politico = {p["id_geo"]: p for p in politico_rows or [] if p.get("id_geo")}
    out = []
    for p in padron_rows:
        idg = p["id_geo"]
        prev = previas.get(idg, {})
        c = censo.get(idg) if censo_rows is not None else None
        pol = politico.get(idg) if politico_rows is not None else None
        out.append({
            "id_geo": idg,
            "departamento": p["departamento"],
            "localidad": p["localidad"],
            "lat": _f(p.get("lat_centro")),
            "lon": _f(p.get("lon_centro")),
            "poblacion": (c or {}).get("poblacion_2022") if censo_rows is not None else prev.get("poblacion"),
            "viviendas": (c or {}).get("viviendas_2022") if censo_rows is not None else prev.get("viviendas"),
            "intendente": (pol or {}).get("intendente") if politico_rows is not None else prev.get("intendente"),
            "partido": (pol or {}).get("partido") if politico_rows is not None else prev.get("partido"),
            "url_ficha": url_ficha(p["departamento"], p["localidad"]),
        })
    return out


def alias(rows: list[Fila]) -> list[Fila]:
    return [
        {"id": r["id"], "texto_normalizado": r["texto_normalizado"],
         "departamento_normalizado": r["departamento_normalizado"] or "", "id_geo": r["id_geo"]}
        for r in rows
    ]


# ── Vivienda ──────────────────────────────────────────────────────────────────

def _checklist_por_entidad(checklist: list[Fila], avance: list[Fila]) -> dict[tuple[str, str], Fila]:
    ultimo_avance: dict[str, Fila] = {}
    for a in avance:
        prev = ultimo_avance.get(a["checklist_id"])
        if prev is None or _fecha(a["fecha_medicion"]) >= _fecha(prev["fecha_medicion"]):
            ultimo_avance[a["checklist_id"]] = a
    out = {}
    for c in checklist:
        av = ultimo_avance.get(c["id"])
        out[(c["programa"], c["entidad_id"])] = {
            "estado_tecnico": c.get("estado_expediente"),
            "avance": (av["porcentaje"] / 100.0) if av else None,
        }
    return out


def vivienda(raw: dict[str, list[Fila]], padron: Padron) -> dict[str, list[Fila]]:
    chk = _checklist_por_entidad(raw["checklist"], raw["avance"])
    montos: dict[tuple[str, str], float | None] = {}
    items: list[Fila] = []
    id_geo_por_entidad: dict[tuple[str, str], str | None] = {}

    for prog in ("cc", "ch", "ml"):
        info = programa_info(prog)
        for r in raw[prog]:
            dep, loc = padron.oficial(r.get("id_geo"), r.get("departamento"), r.get("nombre"))
            c = chk.get((prog, r["id"]), {})
            monto = _f(r.get("monto"))
            montos[(prog, r["id"])] = monto
            id_geo_por_entidad[(prog, r["id"])] = r.get("id_geo")
            items.append({
                "id": f"{prog}:{r['id']}",
                "programa": prog,
                "programa_nombre": info["nombre"],
                "secretaria": info["secretaria"],
                "origen_id": r["id"],
                "nombre": r.get("nombre"),
                "id_geo": r.get("id_geo"),
                "departamento": dep,
                "localidad": loc,
                "estado_origen": r.get("estado_general"),
                "estado_normalizado": estado_normalizado("vivienda", r.get("estado_general")),
                "estado_tecnico": c.get("estado_tecnico"),
                "avance": c.get("avance"),
                "cantidad": r.get("cantidad"),
                "monto": monto,
                "monto_ejecutado": 0.0,
                "monto_usd": None,
                "fecha_inicio": _fecha(r.get("fecha_inicio")),
                "fecha_ultimo_cambio": _dt(r.get("updated_at")),
                "url": info["panel"],
            })

    hitos: list[Fila] = []
    ejecutado: dict[tuple[str, str], float] = defaultdict(float)
    for h in raw["hitos"]:
        clave = (h["programa"], h["entidad_id"])
        if clave not in montos:
            continue  # entidad borrada
        pct = HITOS_PORCENTAJE.get(h["tipo"], 0.0)
        m = montos[clave]
        monto_h = round(m * pct, 2) if m is not None else None
        acreditado = _fecha(h.get("fecha_acreditado"))
        if acreditado and monto_h:
            ejecutado[clave] += monto_h
        hitos.append({
            "id": h["id"], "programa": h["programa"], "origen_id": h["entidad_id"],
            "id_geo": id_geo_por_entidad.get(clave), "hito": h["tipo"], "porcentaje": pct,
            "monto": monto_h, "fecha_acreditado": acreditado,
        })
    for it in items:
        it["monto_ejecutado"] = round(ejecutado.get((it["programa"], it["origen_id"]), 0.0), 2)

    movimientos: list[Fila] = []
    for prog in ("cc", "ch", "ml"):
        for h in raw[f"hist_{prog}"]:
            movimientos.append({
                "id": f"{prog}:{h['id']}", "programa": prog, "origen_id": h["origen_id"],
                "id_geo": id_geo_por_entidad.get((prog, h["origen_id"])),
                "dimension": CAMPO_DIMENSION.get(h["campo"], h["campo"]),
                "estado_anterior": h.get("anterior"), "estado_nuevo": h.get("nuevo"),
                "fecha": _dt(h.get("fecha")),
            })
    # Historial del estado técnico desde el Checklist (spec-estado-tecnico-desde-checklist.md).
    for h in raw["hist_checklist"]:
        movimientos.append({
            "id": f"chk:{h['id']}", "programa": h["programa"], "origen_id": h["origen_id"],
            "id_geo": id_geo_por_entidad.get((h["programa"], h["origen_id"])),
            "dimension": "tecnico", "estado_anterior": None, "estado_nuevo": h.get("nuevo"),
            "fecha": _dt(h.get("fecha")),
        })
    return {"items": items, "hitos": hitos, "movimientos": movimientos}


# ── Privada ───────────────────────────────────────────────────────────────────

ESTADOS_CERRADOS_PRIVADA = {"FINALIZADA", "ARCHIVADO", "LISTA PARA INNAUGURAR", "NO REMITE SUAC"}


def privada(raw: dict[str, list[Fila]], padron: Padron, hoy: date) -> dict[str, list[Fila]]:
    gestiones = []
    geo_por_gestion = {}
    for g in raw["gestiones"]:
        idg = g.get("id_geo") if g.get("id_geo") in padron else None
        dep, loc = padron.oficial(idg, g.get("departamento"), g.get("localidad"))
        ingreso = _fecha(g.get("fecha_ingreso"))
        abierta = g["estado"] not in ESTADOS_CERRADOS_PRIVADA
        geo_por_gestion[g["id"]] = idg
        gestiones.append({
            "id": g["id"], "estado": g["estado"],
            "estado_normalizado": estado_normalizado("privada", g["estado"]),
            "urgencia": g.get("urgencia"), "area": g.get("area"), "ministerio": g.get("ministerio"),
            "categoria": g.get("categoria"), "categoria_general": g.get("categoria_general"),
            "programa": g.get("programa"), "tipo_gestion": g.get("tipo_gestion"),
            "canal_origen": g.get("canal_origen"), "id_geo": idg, "departamento": dep,
            "localidad": loc, "fecha_ingreso": ingreso, "fecha_estado": _dt(g.get("fecha_estado")),
            "fecha_finalizacion": _fecha(g.get("fecha_finalizacion")),
            "dias_abierta": (hoy - ingreso).days if abierta and ingreso else None,
            "ok_gobernador": g.get("ok_gobernador"), "ok_ministro": g.get("ok_ministro"),
            "costo_estimado": _f(g.get("costo_estimado")),
            "detalle": enmascarar(g.get("detalle")),
        })
    movimientos = [
        {
            "id": f"privada:{e['id']}", "programa": "privada", "origen_id": e["origen_id"],
            "id_geo": geo_por_gestion.get(e["origen_id"]), "dimension": "estado",
            "estado_anterior": e.get("anterior"), "estado_nuevo": e.get("nuevo"),
            "fecha": _dt(e.get("fecha")),
        }
        for e in raw["eventos"]
        if e["origen_id"] in geo_por_gestion
    ]
    return {"gestiones": gestiones, "movimientos": movimientos}


# ── Gasífera ──────────────────────────────────────────────────────────────────

def gasifera(raw: dict[str, list[Fila]], padron: Padron) -> dict[str, list[Fila]]:
    locs_por_obra: dict[str, list[Fila]] = defaultdict(list)
    for l in raw["obras_localidades"]:
        locs_por_obra[l["obra_id"]].append(l)
    items = []
    info = programa_info("gas_obra")
    for o in raw["obras"]:
        locs = locs_por_obra.get(o["id"]) or [{"localidad": None, "id_geo": None}]
        n = len(locs)
        estado = o.get("estado_resumen") or o.get("estado_obra")
        monto, usd = _f(o.get("monto")), _f(o.get("monto_usd"))
        for i, l in enumerate(locs):
            dep, loc = padron.oficial(l.get("id_geo"), o.get("departamento"), l.get("localidad"))
            items.append({
                "id": f"gas_obra:{o['id']}:{i}", "programa": "gas_obra",
                "programa_nombre": info["nombre"], "secretaria": info["secretaria"],
                "origen_id": o["id"], "nombre": o.get("nombre"), "id_geo": l.get("id_geo"),
                "departamento": dep, "localidad": loc, "estado_origen": estado,
                "estado_normalizado": estado_normalizado("gasifera", estado),
                "estado_tecnico": None, "avance": _f(o.get("avance")), "cantidad": None,
                "monto": round(monto / n, 2) if monto is not None else None,
                "monto_ejecutado": None,
                "monto_usd": round(usd / n, 2) if usd is not None else None,
                "fecha_inicio": _fecha(o.get("fecha_inicio")),
                "fecha_ultimo_cambio": _dt(o.get("updated_at")), "url": info["panel"],
            })
    info = programa_info("gas_accion")
    for a in raw["acciones"]:
        dep, loc = padron.oficial(a.get("id_geo"), a.get("departamento"), a.get("localidad"))
        items.append({
            "id": f"gas_accion:{a['id']}", "programa": "gas_accion",
            "programa_nombre": info["nombre"], "secretaria": info["secretaria"],
            "origen_id": a["id"], "nombre": a.get("nombre"), "id_geo": a.get("id_geo"),
            "departamento": dep, "localidad": loc, "estado_origen": a.get("estado"),
            "estado_normalizado": estado_normalizado("gasifera", a.get("estado")),
            "estado_tecnico": None, "avance": None, "cantidad": None,
            "monto": _f(a.get("monto")), "monto_ejecutado": None, "monto_usd": _f(a.get("monto_usd")),
            "fecha_inicio": _fecha(a.get("fecha_inicio")),
            "fecha_ultimo_cambio": _dt(a.get("updated_at")), "url": info["panel"],
        })
    return {"items": items}


# ── Gobierno (ATP) ────────────────────────────────────────────────────────────

def _estado_atp(monto: float | None, entregado: float) -> str:
    """Mismo criterio que svc-vivienda `resumen_territorial.aggregations.resumen_atp_estado`."""
    if not monto or monto <= 0 or entregado <= 0:
        return "Pendiente"
    return "Pagado" if entregado >= monto else "Parcial"


def gralgob(
    raw: dict[str, list[Fila]], padron: Padron, indec_a_geo: dict[str, str]
) -> dict[str, list[Fila]]:
    pagado: dict[str, float] = defaultdict(float)
    for c in raw["cronograma"]:
        pagado[c["compromiso_id"]] += _f(c["monto"]) or 0.0
    info = programa_info("atp")
    items, pagos = [], []
    geo_por_compromiso = {}
    for c in raw["compromisos"]:
        dep, loc = padron.oficial(c.get("id_geo"), c.get("departamento"), c.get("localidad"))
        geo_por_compromiso[c["id"]] = (c.get("id_geo"), dep, loc)
        monto = _f(c.get("monto"))
        # El signo se espeja del Sheet (negativo = pagado): valor absoluto, igual que el panel.
        entregado = abs(pagado.get(c["id"], 0.0))
        estado = _estado_atp(monto, entregado)
        items.append({
            "id": f"atp:{c['id']}", "programa": "atp", "programa_nombre": info["nombre"],
            "secretaria": info["secretaria"], "origen_id": c["id"], "nombre": c.get("nombre"),
            "id_geo": c.get("id_geo"), "departamento": dep, "localidad": loc,
            "estado_origen": estado, "estado_normalizado": estado_normalizado("atp", estado),
            "estado_tecnico": None, "avance": None, "cantidad": None, "monto": monto,
            "monto_ejecutado": round(entregado, 2), "monto_usd": None,
            "fecha_inicio": _fecha(c.get("fecha_inicio")),
            "fecha_ultimo_cambio": _dt(c.get("updated_at")), "url": info["panel"],
        })
    for c in raw["cronograma"]:
        idg, dep, loc = geo_por_compromiso.get(c["compromiso_id"], (None, None, None))
        pagos.append({
            "id": c["id"], "fuente": "compromiso", "origen_id": c["compromiso_id"],
            "id_geo": idg, "departamento": dep, "localidad": loc,
            "fecha": _fecha(c["periodo"]), "monto": abs(_f(c["monto"]) or 0.0),
        })
    for p in raw["interno"]:
        idg = indec_a_geo.get(p.get("codigo_indec") or "")
        dep, loc = padron.oficial(idg, p.get("departamento"), p.get("localidad"))
        pagos.append({
            "id": p["id"], "fuente": "interno", "origen_id": None, "id_geo": idg,
            "departamento": dep, "localidad": loc, "fecha": _fecha(p.get("fecha")),
            "monto": _f(p["monto"]) or 0.0,
        })
    return {"items": items, "pagos": pagos}


# ── Datos externos ────────────────────────────────────────────────────────────

def transferencias(rows: list[Fila], padron: Padron) -> list[Fila]:
    out = []
    for t in rows:
        dep, loc = padron.oficial(t.get("id_geo"), t.get("departamento"), t.get("localidad"))
        out.append({
            "id": t["id"], "id_geo": t.get("id_geo"), "departamento": dep, "localidad": loc,
            "tipo": t.get("tipo"), "concepto": t["concepto"], "periodo": _fecha(t["periodo"]),
            "monto": _f(t["monto"]) or 0.0,
        })
    return out


def indec_a_geo(censo_rows: Iterable[Fila]) -> dict[str, str]:
    return {c["codigo_indec"]: c["id_geo"] for c in censo_rows if c.get("codigo_indec") and c.get("id_geo")}
