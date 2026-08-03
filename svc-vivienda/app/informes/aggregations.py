"""Funciones puras de agregación para los informes por programa.

Deliberadamente no tocan la DB ni el ORM: reciben listas de dicts simples y
devuelven listas de dicts simples. Así se pueden testear sin fixture de DB y
se reusan igual para Cordón Cuneta y Córdoba Hogar — son ~95% el mismo
modelo de datos (municipio/localidad + departamento + estado_general), la
diferencia entre programas queda afuera, en `service.py`.
"""
from collections import Counter, defaultdict
from typing import Any, TypedDict

from app.geo.matching import normalize_name


class EntidadDict(TypedDict, total=False):
    id: str
    nombre: str
    departamento: str | None
    estado_general: int | None
    expediente: str | None
    monto: float | None


class CatalogoEstado(TypedDict):
    label: str
    bg: str
    text_color: str
    orden: int


SIN_ESTADO = {"label": "Sin estado", "bg": "#e5e7eb", "text_color": "#374151"}


def kpis_por_estado(
    entidades: list[EntidadDict], catalogo: dict[int, CatalogoEstado]
) -> list[dict[str, Any]]:
    """Conteo de entidades por estado_general, en el orden del catálogo (`orden`).
    Las entidades sin estado_general se agrupan aparte, al final."""
    conteo = Counter(e.get("estado_general") for e in entidades)
    resultado = []
    for estado_id, cat in sorted(catalogo.items(), key=lambda kv: kv[1]["orden"]):
        resultado.append({
            "estado_id": estado_id,
            "label": cat["label"],
            "bg": cat["bg"],
            "text_color": cat["text_color"],
            "cantidad": conteo.get(estado_id, 0),
        })
    sin_estado = conteo.get(None, 0)
    if sin_estado:
        resultado.append({"estado_id": None, "cantidad": sin_estado, **SIN_ESTADO})
    return resultado


def cobertura_por_departamento(
    entidades: list[EntidadDict], geo_localidades: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Por departamento: cuántas entidades activas tiene el programa vs. cuántas
    localidades activas totales hay en viv_geo_localidades para ese depto.

    No hace falta matchear entidad↔localidad una por una para "cubiertas": la
    unicidad de (municipio/localidad, departamento) ya está garantizada por
    constraint de DB entre registros activos (migraciones 0014/0015) — así que
    cada entidad ES una localidad distinta cubierta en su departamento.
    """
    # El nombre "oficial" de un departamento es el del padrón geo (mismo que usa
    # el GeoJSON de departamentos del mapa coroplético) — se construye primero
    # para que gane sobre la grafía que haya tipeado el usuario al cargar un
    # municipio/localidad (ej. "CAPITAL" vs "Capital").
    display_name: dict[str, str] = {}
    totales: Counter[str] = Counter()
    for g in geo_localidades:
        if not g.get("activo", True):
            continue
        dep = g.get("departamento")
        if not dep:
            continue
        key = normalize_name(dep)
        totales[key] += 1
        display_name.setdefault(key, dep)

    conteo_entidad: Counter[str] = Counter()
    for e in entidades:
        dep = e.get("departamento")
        if not dep:
            continue
        key = normalize_name(dep)
        conteo_entidad[key] += 1
        display_name.setdefault(key, dep)

    resultado = []
    for key in sorted(set(conteo_entidad) | set(totales), key=lambda k: display_name.get(k, k)):
        cantidad = conteo_entidad.get(key, 0)
        total = totales.get(key, 0)
        resultado.append({
            "departamento": display_name[key],
            "cantidad": cantidad,
            "localidades_cubiertas": cantidad,
            "localidades_totales": total,
            "pct_cobertura": round(cantidad / total * 100, 1) if total else 0.0,
        })
    return resultado


def evolucion_temporal(historial: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cantidad de cambios de estado (cualquier dimensión) por mes, a partir del
    historial. Usa `created_at` — que puede haber sido fijado a una fecha
    pasada explícita por el usuario vía `fecha_cambio` (ver EditModal CC/CH),
    así que refleja la fecha real del cambio, no la de carga en el sistema."""
    conteo: Counter[str] = Counter()
    for h in historial:
        mes = h["created_at"].strftime("%Y-%m")
        conteo[mes] += 1
    return [{"mes": mes, "cantidad_cambios": conteo[mes]} for mes in sorted(conteo)]


def puntos_mapa(
    entidades: list[EntidadDict],
    geo_localidades: list[dict[str, Any]],
    catalogo: dict[int, CatalogoEstado],
) -> list[dict[str, Any]]:
    """Un punto por entidad, con lat/lon matcheado best-effort contra
    viv_geo_localidades por (departamento, nombre) normalizado. Sin match →
    lat/lon quedan en None (el frontend simplemente no lo dibuja en el mapa,
    no rompe nada — mismo criterio tolerante que checklist_sync.py)."""
    geo_index: dict[tuple[str, str], dict[str, Any]] = {}
    for g in geo_localidades:
        key = (normalize_name(g.get("departamento")), normalize_name(g.get("localidad")))
        geo_index[key] = g

    puntos = []
    for e in entidades:
        dep = e.get("departamento")
        key = (normalize_name(dep), normalize_name(e.get("nombre")))
        g = geo_index.get(key)
        lat = g.get("lat_centro") if g else None
        lon = g.get("lon_centro") if g else None
        estado = catalogo.get(e.get("estado_general")) if e.get("estado_general") is not None else None
        puntos.append({
            "id": e["id"],
            "nombre": e["nombre"],
            "departamento": dep,
            "lat": float(lat) if lat is not None else None,
            "lon": float(lon) if lon is not None else None,
            "estado_general_id": e.get("estado_general"),
            "estado_label": estado["label"] if estado else None,
            "estado_bg": estado["bg"] if estado else None,
            "estado_text_color": estado["text_color"] if estado else None,
            "expediente": e.get("expediente"),
            "monto": float(e["monto"]) if e.get("monto") is not None else None,
        })
    return puntos
