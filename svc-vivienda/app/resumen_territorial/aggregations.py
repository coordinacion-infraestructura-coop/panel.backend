"""Funciones puras de agregación del Resumen Territorial.

No tocan la DB ni el ORM: reciben listas de dicts simples y devuelven dicts
simples, para poder testearse sin fixture de base. Espeja
`app/informes/aggregations.py`.

Spec: docs/files/spec-resumen-territorial.md §6.1
"""
from __future__ import annotations

from typing import Any, Iterable

from app.checklist_tecnico import catalog
from app.geo.matching import candidatos_localidad, normalize_departamento, normalize_name

# ── Constantes de programa ────────────────────────────────────────────────────

PROGRAMA_A_CHECKLIST: dict[str, str] = {
    "cordon_cuneta": "cc",
    "cordoba_hogar": "ch",
    "mi_lugar": "ml",
}
PROGRAMA_LABEL: dict[str, str] = {
    "cordon_cuneta": "Cordón Cuneta y Adoquinado",
    "cordoba_hogar": "Córdoba Hogar",
    "mi_lugar": "Mi Lugar",
    "gestiones": "Gestiones — Sec. Privada",
    "acciones_territorio": "Obras de Gas — Sec. Gasífera",
    "atp": "ATP — Sec. Gral. de Gobierno",
}

_AREA_ORDER = {"vivienda": 0, "privada": 1, "gasifera": 2, "gralgob": 3}
_PROGRAMA_ORDER = {
    "cordon_cuneta": 0, "cordoba_hogar": 1, "mi_lugar": 2, "gestiones": 3,
    "acciones_territorio": 4, "atp": 5,
}

SIN_ESTADO = {"label": "Sin estado", "bg": "#e5e7eb", "text_color": "#374151"}

# ── Privada: estados de `cat_estado` (svc-privada) ───────────────────────────
# El sistema de la Secretaría Privada no expone colores por estado (a diferencia
# de viv_{cc,ch,ml}_estados), así que se fijan acá. Estados tomados de
# EstadoGestion (frontend privada) / doc arquitectura_actual.md.
PRIVADA_ESTADOS_CERRADOS = frozenset({"FINALIZADA", "ARCHIVADO"})
_PRIVADA_META_EN_CURSO = {"label": "En curso", "bg": "#dceffb", "text_color": "#036aa1"}
_PRIVADA_META_CERRADAS = {"label": "Finalizadas", "bg": "#dcf5e3", "text_color": "#15803d"}
_PRIVADA_META_MIXTO = {"label": "Mixto", "bg": "#fdf0d5", "text_color": "#b45309"}


def resumen_privada_estado(por_estado: dict[str, int]) -> dict[str, str]:
    """Deriva un badge (label + colores) para la línea roll-up de Privada de una
    localidad, a partir del conteo de gestiones por estado."""
    total = sum(por_estado.values())
    cerradas = sum(v for k, v in por_estado.items() if str(k).upper() in PRIVADA_ESTADOS_CERRADOS)
    activas = total - cerradas
    if total == 0:
        return {**SIN_ESTADO}
    if activas == 0:
        return dict(_PRIVADA_META_CERRADAS)
    if cerradas == 0:
        return dict(_PRIVADA_META_EN_CURSO)
    return dict(_PRIVADA_META_MIXTO)


def _plural_gestiones(n: int) -> str:
    return f"{n} gestión" if n == 1 else f"{n} gestiones"


def detalle_privada(por_estado: dict[str, int]) -> str:
    """Texto corto tipo '5 gestiones · 3 en curso, 2 finalizadas'."""
    total = sum(por_estado.values())
    cerradas = sum(v for k, v in por_estado.items() if str(k).upper() in PRIVADA_ESTADOS_CERRADOS)
    activas = total - cerradas
    partes = []
    if activas:
        partes.append(f"{activas} en curso")
    if cerradas:
        partes.append(f"{cerradas} finalizada{'s' if cerradas != 1 else ''}")
    sufijo = f" · {', '.join(partes)}" if partes else ""
    return f"{_plural_gestiones(total)}{sufijo}"


# ── Gasífera: acciones territoriales de gas (svc-gasifera, ADR-017) ──────────
# Mismo criterio que Privada arriba: el badge se deriva de un conteo simple
# cumplida/en curso, no hay catálogo de estados con colores propios.
_GASIFERA_ESTADOS_CERRADOS = frozenset({"CUMPLIDO"})
_GASIFERA_META_EN_CURSO = {"label": "En curso", "bg": "#fdf0d5", "text_color": "#b45309"}
_GASIFERA_META_CERRADAS = {"label": "Cumplidas", "bg": "#dcf5e3", "text_color": "#15803d"}
_GASIFERA_META_MIXTO = {"label": "Mixto", "bg": "#fdf0d5", "text_color": "#b45309"}


def resumen_gasifera_estado(por_estado: dict[str, int]) -> dict[str, str]:
    """Deriva un badge (label + colores) para la línea roll-up de Gasífera de
    una localidad, a partir del conteo de acciones cumplidas/en curso."""
    total = sum(por_estado.values())
    cerradas = sum(v for k, v in por_estado.items() if str(k).upper() in _GASIFERA_ESTADOS_CERRADOS)
    activas = total - cerradas
    if total == 0:
        return {**SIN_ESTADO}
    if activas == 0:
        return dict(_GASIFERA_META_CERRADAS)
    if cerradas == 0:
        return dict(_GASIFERA_META_EN_CURSO)
    return dict(_GASIFERA_META_MIXTO)


def _plural_acciones(n: int) -> str:
    return f"{n} acción" if n == 1 else f"{n} acciones"


def detalle_gasifera(por_estado: dict[str, int]) -> str:
    """Texto corto tipo '5 acciones · 3 en curso, 2 cumplidas'."""
    total = sum(por_estado.values())
    cerradas = sum(v for k, v in por_estado.items() if str(k).upper() in _GASIFERA_ESTADOS_CERRADOS)
    activas = total - cerradas
    partes = []
    if activas:
        partes.append(f"{activas} en curso")
    if cerradas:
        partes.append(f"{cerradas} cumplida{'s' if cerradas != 1 else ''}")
    sufijo = f" · {', '.join(partes)}" if partes else ""
    return f"{_plural_acciones(total)}{sufijo}"


# ── ATP: compromisos del Aporte del Tesoro Provincial (svc-gralgob) ──────────
# A diferencia de Privada/Gasífera (badge derivado de un conteo por estado),
# ATP no tiene "estados" — el badge se deriva de cuánto del monto anunciado ya
# fue entregado (cronograma de pagos), mismo espíritu (activo/mixto/cerrado).
_ATP_META_PENDIENTE = {"label": "Pendiente", "bg": "#fee2e2", "text_color": "#b91c1c"}
_ATP_META_PARCIAL = {"label": "Parcial", "bg": "#fdf0d5", "text_color": "#b45309"}
_ATP_META_PAGADO = {"label": "Pagado", "bg": "#dcf5e3", "text_color": "#15803d"}


def resumen_atp_estado(monto_total: float | None, entregado: float) -> dict[str, str]:
    """Deriva un badge (label + colores) para la línea roll-up de ATP de una
    localidad, a partir del monto total anunciado vs. lo ya entregado."""
    if not monto_total or monto_total <= 0:
        return {**SIN_ESTADO}
    if entregado <= 0:
        return dict(_ATP_META_PENDIENTE)
    if entregado >= monto_total:
        return dict(_ATP_META_PAGADO)
    return dict(_ATP_META_PARCIAL)


def detalle_atp(total_compromisos: int, derivados: int) -> str:
    """Texto corto tipo '3 compromisos · 1 derivado'."""
    partes = [f"{total_compromisos} compromiso{'s' if total_compromisos != 1 else ''}"]
    if derivados:
        partes.append(f"{derivados} derivado{'s' if derivados != 1 else ''}")
    return " · ".join(partes)


# ── Checklist ────────────────────────────────────────────────────────────────

def items_faltantes(
    items_rows: Iterable[dict[str, Any]], programa_cod: str
) -> tuple[int, int, list[str], bool]:
    """Devuelve (total, faltan, labels_faltantes, iniciado).

    `programa_cod` es 'cc'|'ch'|'ml'. Si `items_rows` está vacío → el checklist
    nunca se abrió: (total, total, [], False). Si no → cuenta los ítems con
    `valor != 'completo'`.
    """
    total = len(catalog.todos_los_item_keys(programa_cod))
    rows = list(items_rows)
    if not rows:
        return total, total, [], False
    faltan = [r for r in rows if r.get("valor") != "completo"]
    labels = [
        lbl
        for r in faltan
        if (lbl := catalog.item_label(programa_cod, r["item_num"], r.get("sub_item_num")))
    ]
    return total, len(faltan), labels, True


# ── Última comunicación ──────────────────────────────────────────────────────

def _created_sort_key(row: dict[str, Any]) -> float:
    ts = row.get("created_at")
    try:
        return ts.timestamp() if ts is not None else 0.0
    except (AttributeError, OSError, ValueError):
        return 0.0


def ultima_comunicacion(pedidos_rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Última comunicación de una entidad, por (fecha_pedido, created_at). Sin
    enmascarar — el enmascarado por visibilidad se hace en el GET (§7)."""
    rows = list(pedidos_rows)
    if not rows:
        return None
    p = max(rows, key=lambda r: (r["fecha_pedido"], _created_sort_key(r)))
    return {
        "fecha": p["fecha_pedido"],
        "texto": p.get("descripcion"),
        "area": p.get("secretaria"),
        "autor": p.get("created_by_nombre") or p.get("created_by"),
    }


# ── Agrupación por localidad ─────────────────────────────────────────────────

def _programa_sort_key(prog: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _AREA_ORDER.get(prog.get("area"), 9),
        _PROGRAMA_ORDER.get(prog.get("programa"), 9),
        (prog.get("detalle") or ""),
    )


def agrupar_por_localidad(
    lineas: Iterable[dict[str, Any]], geo_localidades: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Agrupa líneas de programa por localidad.

    Cada `linea` es `{"departamento": str|None, "nombre_localidad": str,
    "id_geo": str|None, "programa": {...}}` donde `programa` es el dict que se
    vuelve `ResumenPrograma`. La clave de agrupación prioriza `id_geo` cuando
    la línea lo trae resuelto (Vivienda/Gasífera/ATP, ver ADR-024) — dos
    líneas con el mismo `id_geo` se agrupan aunque su texto crudo difiera.

    Para líneas sin `id_geo` propio (Privada, que no participa de ADR-024, o
    legado no backfillado) se intenta resolver contra el padrón por texto
    — `(normalize_departamento(departamento), candidato)` probando cada
    variante de `candidatos_localidad(nombre)` contra ambos lados — y, si
    matchea, se usa el `id_geo` de ESE resultado como clave (mismo namespace
    que las líneas ya resueltas). Esto es crítico: sin esto, una línea de
    Privada con texto idéntico a una de Vivienda para la misma localidad real
    (ej. "ALICIA" en depto "SAN JUSTO") NO se unificaba, porque una usaba
    clave `geo:<id>` y la otra una clave de texto aparte — bug encontrado con
    datos reales 2026-09-28. Sólo cuando el texto tampoco matchea nada del
    padrón se cae a una clave puramente textual (`txt:...`), como antes.
    El nombre de display siempre prioriza la grafía del padrón
    `viv_geo_localidades` cuando hay un id_geo de por medio.
    """
    geo_por_id: dict[str, tuple[str | None, str]] = {}
    geo_full: dict[tuple[str, str], tuple[str, str | None, str]] = {}
    geo_depto: dict[str, str] = {}
    for g in geo_localidades:
        dep = g.get("departamento")
        loc = g.get("localidad")
        g_id = g.get("id_geo")
        if not loc:
            continue
        dk = normalize_departamento(dep)
        for lk in candidatos_localidad(loc):
            geo_full.setdefault((dk, lk), (g_id, dep, loc))
        if dep:
            geo_depto.setdefault(dk, dep)
        if g_id:
            geo_por_id.setdefault(g_id, (dep, loc))

    grupos: dict[str, dict[str, Any]] = {}
    for linea in lineas:
        dep_raw = linea.get("departamento")
        loc_raw = linea["nombre_localidad"]
        id_geo = linea.get("id_geo")

        if not id_geo:
            # Sin id_geo propio: intentar resolver contra el padrón por texto
            # antes de resignarse a una clave textual (ver docstring).
            dk = normalize_departamento(dep_raw)
            for candidato in candidatos_localidad(loc_raw):
                match = geo_full.get((dk, candidato))
                if match:
                    id_geo = match[0]
                    break

        if id_geo:
            key = f"geo:{id_geo}"
            dep_disp, loc_disp = geo_por_id.get(id_geo, (dep_raw, loc_raw))
        else:
            dk = normalize_departamento(dep_raw)
            lk = normalize_name(loc_raw)
            dep_disp = geo_depto.get(dk) or (dep_raw or None)
            loc_disp = loc_raw
            key = f"txt:{dk}|{lk}"

        if key not in grupos:
            grupos[key] = {
                "id_geo": id_geo,
                "localidad": loc_disp,
                "departamento": dep_disp,
                "programas": [],
            }
        grupos[key]["programas"].append(linea["programa"])

    resultado = list(grupos.values())
    for g in resultado:
        g["programas"].sort(key=_programa_sort_key)
    resultado.sort(
        key=lambda g: (
            (g["departamento"] or "￿").lower(),
            g["localidad"].lower(),
        )
    )
    return resultado


# ── Padrón geográfico: denominador de cobertura por departamento ────────────

def contar_localidades_por_departamento(geo_localidades: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Total de localidades ACTIVAS del padrón por departamento
    (`viv_geo_localidades`, ADR-024) — denominador del % de cobertura del
    tablero territorial (Etapa 3, spec-resumen-territorial-tablero-v2.md §4).
    `ResumenTerritorialPayload.localidades` sólo trae localidades con al menos
    un programa; sin este conteo no hay forma de saber contra cuántas
    localidades reales se está cubriendo. No renormaliza el nombre del
    departamento — usa la grafía tal cual está en el padrón, para calzar con
    `ResumenLocalidad.departamento` cuando viene resuelto por id_geo."""
    conteo: dict[str, int] = {}
    for g in geo_localidades:
        if not g.get("activo", True):
            continue
        dep = g.get("departamento")
        if not dep:
            continue
        conteo[dep] = conteo.get(dep, 0) + 1
    return conteo


# ── Enriquecimiento con datos externos (Censo 2022 + transferencias, ADR-025) ─

def enriquecer_con_datos_externos(
    localidad: dict[str, Any], datos_externos_por_id_geo: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Agrega población/viviendas (Censo 2022) y transferencias (último
    período cargado) a una localidad ya agrupada, por `id_geo` —
    `svc-datos-externos` (ADR-025). Sin `id_geo` propio o sin match en la
    fuente, la localidad queda con estos campos en `None` — no bloquea nada
    aguas abajo, mismo criterio tolerante que el resto de las fuentes
    federadas. Pura: recibe y devuelve dicts simples, no toca DB.

    `transferencias_total` se deja siempre disponible junto al per cápita
    (no sólo este último) porque en comunas chicas el componente fijo de la
    fórmula de coparticipación dispara valores per cápita altos y engañosos
    — el frontend debe poder mostrar ambos lado a lado (spec §4, Etapa 5).
    """
    id_geo = localidad.get("id_geo")
    datos = datos_externos_por_id_geo.get(id_geo) if id_geo else None

    poblacion = datos.get("poblacion_2022") if datos else None
    transferencias_total = datos.get("transferencias_total") if datos else None

    atp_monto = sum(
        p["monto"]
        for p in localidad["programas"]
        if p.get("programa") == "atp" and p.get("monto") is not None
    )

    return {
        **localidad,
        "categoria": (datos or {}).get("categoria"),
        "poblacion_2022": poblacion,
        "viviendas_2022": (datos or {}).get("viviendas_2022"),
        "transferencias_periodo": (datos or {}).get("transferencias_periodo"),
        "transferencias_total": transferencias_total,
        "transferencias_per_capita": (
            round(transferencias_total / poblacion, 2)
            if transferencias_total is not None and poblacion else None
        ),
        "atp_monto_per_capita": (
            round(atp_monto / poblacion, 2) if atp_monto and poblacion else None
        ),
    }


def focalizacion_atp_por_departamento(
    localidades: Iterable[dict[str, Any]]
) -> dict[str, float]:
    """Índice de focalización ATP por departamento: (% de la inversión ATP
    provincial que recibió el depto) / (% de la población provincial que
    vive en el depto) — spec-resumen-territorial-tablero-v2.md §3. >1 implica
    que el depto recibe más ATP del que le tocaría en proporción a su
    población; <1, menos.

    Recibe localidades YA enriquecidas (`enriquecer_con_datos_externos`, con
    `poblacion_2022` seteado cuando hay match). Función pura, testeada, pero
    todavía **no está expuesta en el payload de `GET /resumen-territorial`**
    — no hay hoy una sección "por departamento" en el schema y agregarla sin
    que la Etapa 3 (vista Provincia) haya fijado su forma de consumo sería
    inventar API de más. Queda lista para que esa etapa la use, vía un nuevo
    campo/endpoint que se decida en ese momento.
    """
    por_depto_atp: dict[str, float] = {}
    por_depto_poblacion: dict[str, int] = {}
    for loc in localidades:
        dep = loc.get("departamento")
        if not dep:
            continue
        atp = sum(
            p["monto"]
            for p in loc.get("programas", [])
            if p.get("programa") == "atp" and p.get("monto") is not None
        )
        if atp:
            por_depto_atp[dep] = por_depto_atp.get(dep, 0.0) + atp
        poblacion = loc.get("poblacion_2022")
        if poblacion:
            por_depto_poblacion[dep] = por_depto_poblacion.get(dep, 0) + poblacion

    total_atp = sum(por_depto_atp.values())
    total_poblacion = sum(por_depto_poblacion.values())
    if not total_atp or not total_poblacion:
        return {}

    resultado: dict[str, float] = {}
    for dep, poblacion in por_depto_poblacion.items():
        pct_atp = por_depto_atp.get(dep, 0.0) / total_atp
        pct_poblacion = poblacion / total_poblacion
        if pct_poblacion:
            resultado[dep] = round(pct_atp / pct_poblacion, 3)
    return resultado
