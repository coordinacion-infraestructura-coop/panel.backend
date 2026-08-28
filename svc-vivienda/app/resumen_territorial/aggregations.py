"""Funciones puras de agregación del Resumen Territorial.

No tocan la DB ni el ORM: reciben listas de dicts simples y devuelven dicts
simples, para poder testearse sin fixture de base. Espeja
`app/informes/aggregations.py`.

Spec: docs/files/spec-resumen-territorial.md §6.1
"""
from __future__ import annotations

from typing import Any, Iterable

from app.checklist_tecnico import catalog
from app.geo.matching import normalize_name

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
}

_AREA_ORDER = {"vivienda": 0, "privada": 1}
_PROGRAMA_ORDER = {"cordon_cuneta": 0, "cordoba_hogar": 1, "mi_lugar": 2, "gestiones": 3}

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
    "programa": {...}}` donde `programa` es el dict que se vuelve `ResumenPrograma`.
    La clave de agrupación es `(normalize_name(departamento), normalize_name(nombre))`
    (mismo criterio que `informes/aggregations.py:puntos_mapa`). El nombre de
    display prioriza la grafía del padrón `viv_geo_localidades`.
    """
    geo_full: dict[tuple[str, str], tuple[str, str]] = {}
    geo_depto: dict[str, str] = {}
    for g in geo_localidades:
        dep = g.get("departamento")
        loc = g.get("localidad")
        if not loc:
            continue
        dk, lk = normalize_name(dep), normalize_name(loc)
        geo_full.setdefault((dk, lk), (dep, loc))
        if dep:
            geo_depto.setdefault(dk, dep)

    grupos: dict[tuple[str, str], dict[str, Any]] = {}
    for linea in lineas:
        dep_raw = linea.get("departamento")
        loc_raw = linea["nombre_localidad"]
        dk, lk = normalize_name(dep_raw), normalize_name(loc_raw)
        key = (dk, lk)
        if key not in grupos:
            dep_disp, loc_disp = geo_full.get(key, (None, None))
            if loc_disp is None:
                loc_disp = loc_raw
            if dep_disp is None:
                dep_disp = geo_depto.get(dk) or (dep_raw or None)
            grupos[key] = {
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
