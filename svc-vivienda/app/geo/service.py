"""Resolución de localidades crudas contra el padrón oficial
(`viv_geo_localidades`) + la tabla de vinculación manual
(`viv_geo_alias_manual`). Único lugar de verdad para el matching — usado por
`POST /internal/geo/resolver-localidades` (llamado por Gasífera/Gralgob en
sync-time) y en proceso por `cordon_cuneta`/`cordoba_hogar` al crear/editar
(sin llamada de red, mismo servicio que el padrón).

Ver docs/files/spec-normalizacion-localidades.md §4.3/§4.9, ADR-024.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser
from app.geo.matching import candidatos_localidad, normalize_departamento, normalize_name
from app.geo.models import GeoAliasManual, GeoLocalidad, GeoPendiente
from app.notificaciones import service as notificaciones_service

logger = logging.getLogger(__name__)

# Actor sintético para notificaciones disparadas por el propio resolver (no
# hay JWT en este flujo — mismo patrón que `_SCHEDULER_ACTOR` en
# app/internal/router.py).
_RESOLVER_ACTOR = AuthUser(uid="geo-resolver", email="geo-resolver", role="system", secretarias=[])


@dataclass(frozen=True)
class LocalidadResuelta:
    departamento_in: str | None
    localidad_in: str | None
    id_geo: str | None
    departamento_oficial: str | None
    localidad_oficial: str | None
    match_tipo: str  # "manual" | "exacto" | "alias" | "sin_match"


async def _cargar_padron(db: AsyncSession) -> tuple[dict[str, list[GeoLocalidad]], dict[str, GeoLocalidad]]:
    """Indexa el padrón no sólo por su nombre normalizado exacto, sino por
    todos los candidatos de `candidatos_localidad()` (alias entre paréntesis
    o separados por guion en el propio nombre del padrón, ej. "CHARRAS (Villa
    Colón)") — así una fuente que sólo escribe "CHARRAS" también matchea.
    Antes esto sólo se expandía del lado del nombre de entrada, nunca del
    lado del padrón (bug encontrado con datos reales, 2026-09-28)."""
    rows = (await db.execute(select(GeoLocalidad))).scalars().all()
    por_nombre: dict[str, list[GeoLocalidad]] = {}
    por_id: dict[str, GeoLocalidad] = {}
    for g in rows:
        por_id[g.id_geo] = g
        if g.activo:
            for key in candidatos_localidad(g.localidad):
                por_nombre.setdefault(key, []).append(g)
    return por_nombre, por_id


async def listar_padron(db: AsyncSession) -> list[dict]:
    """Padrón oficial completo (activas e inactivas) para los servicios que
    mantienen un espejo de solo lectura — hoy svc-privada (ADR-026,
    docs/files/spec-privada-padron-oficial.md)."""
    rows = (
        await db.execute(select(GeoLocalidad).order_by(GeoLocalidad.departamento, GeoLocalidad.localidad))
    ).scalars().all()
    return [
        {
            "id_geo": g.id_geo,
            "departamento": g.departamento,
            "localidad": g.localidad,
            "lat_centro": float(g.lat_centro) if g.lat_centro is not None else None,
            "lon_centro": float(g.lon_centro) if g.lon_centro is not None else None,
            "activo": g.activo,
        }
        for g in rows
    ]


async def _cargar_alias(db: AsyncSession) -> dict[tuple[str, str], GeoAliasManual]:
    """Alias vigentes por `(texto, departamento)`; departamento `""` = alias
    global (spec-geo-asignacion-manual-localidades.md §3.2)."""
    rows = (
        await db.execute(select(GeoAliasManual).where(GeoAliasManual.deleted_at.is_(None)))
    ).scalars().all()
    return {(a.texto_normalizado, a.departamento_normalizado): a for a in rows}


def _elegir(candidatos: list[GeoLocalidad], departamento_in: str | None) -> GeoLocalidad | None:
    """Desambigua cuando el nombre normalizado matchea más de una fila del
    padrón (localidades homónimas en departamentos distintos). Nunca adivina:
    si el departamento de entrada no alcanza para desambiguar, no hay match."""
    if len(candidatos) == 1:
        return candidatos[0]
    if departamento_in:
        dep_norm = normalize_departamento(departamento_in)
        exactos = [g for g in candidatos if normalize_departamento(g.departamento) == dep_norm]
        if len(exactos) == 1:
            return exactos[0]
    return None


def _resolver_uno(
    departamento_in: str | None,
    localidad_in: str | None,
    padron: dict[str, list[GeoLocalidad]],
    alias: dict[tuple[str, str], GeoAliasManual],
    por_id: dict[str, GeoLocalidad],
) -> LocalidadResuelta:
    if not localidad_in:
        return LocalidadResuelta(departamento_in, localidad_in, None, None, None, "sin_match")

    loc_norm = normalize_name(localidad_in)

    # Primero el alias acotado al departamento de entrada, después el global.
    a = alias.get((loc_norm, normalize_departamento(departamento_in))) or alias.get((loc_norm, ""))
    if a is not None:
        geo = por_id.get(a.id_geo) if a.id_geo else None
        return LocalidadResuelta(
            departamento_in, localidad_in, a.id_geo,
            geo.departamento if geo else None, geo.localidad if geo else None,
            "manual",
        )

    candidatos_norm = [(loc_norm, "exacto")]
    candidatos_norm += [(k, "alias") for k in candidatos_localidad(localidad_in) if k != loc_norm]
    for candidato_norm, tipo in candidatos_norm:
        filas = padron.get(candidato_norm)
        if not filas:
            continue
        elegido = _elegir(filas, departamento_in)
        if elegido:
            return LocalidadResuelta(
                departamento_in, localidad_in, elegido.id_geo,
                elegido.departamento, elegido.localidad, tipo,
            )

    return LocalidadResuelta(departamento_in, localidad_in, None, None, None, "sin_match")


ENLACE_PENDIENTES = "/admin/localidades-sin-resolver"


async def _registrar_pendientes(
    db: AsyncSession,
    origen: str | None,
    sin_match: list[tuple[str | None, str | None, int | None]],
) -> list[tuple[str | None, str | None]]:
    """Upsert en `viv_geo_pendientes` de lo que no resolvió en esta corrida.
    Devuelve los pares que son novedad (pendiente nuevo, o uno resuelto /
    descartado que volvió a aparecer) — sólo esos se notifican."""
    origen_label = origen or "desconocido"
    agrupado: dict[tuple[str, str], list] = {}
    for dep, loc, cantidad in sin_match:
        clave = (normalize_departamento(dep), normalize_name(loc))
        g = agrupado.setdefault(clave, [dep, loc, 0])
        g[2] += cantidad if cantidad is not None else 1

    existentes = {
        (p.departamento_normalizado, p.texto_normalizado): p
        for p in (
            await db.execute(select(GeoPendiente).where(GeoPendiente.origen == origen_label))
        ).scalars().all()
    }
    now = datetime.now(timezone.utc)
    novedades: list[tuple[str | None, str | None]] = []
    for clave, (dep, loc, cantidad) in agrupado.items():
        p = existentes.get(clave)
        if p is None:
            db.add(GeoPendiente(
                origen=origen_label, departamento_original=dep, localidad_original=loc,
                departamento_normalizado=clave[0], texto_normalizado=clave[1],
                cantidad=cantidad, primera_vez=now, ultima_vez=now,
            ))
            novedades.append((dep, loc))
            continue
        p.departamento_original, p.localidad_original = dep, loc
        p.cantidad, p.ultima_vez = cantidad, now
        if p.estado != "pendiente":
            p.estado, p.alias_id, p.resuelta_at, p.resuelta_by = "pendiente", None, None, None
            novedades.append((dep, loc))
    await db.flush()
    return novedades


async def _notificar_sin_match(
    db: AsyncSession, origen: str | None, sin_match: list[tuple[str | None, str | None]]
) -> None:
    """Best-effort: una notificación batcheada al rol Admin con las
    localidades que aparecen por primera vez como pendientes (las que ya
    estaban en `viv_geo_pendientes` no vuelven a notificar en cada corrida).
    Una falla acá nunca debe interrumpir el flujo que llamó al resolver."""
    origen_label = origen or "desconocido"
    ejemplos = "; ".join(
        f"{loc or '(vacío)'} ({dep or 'sin depto'})" for dep, loc in sin_match[:10]
    )
    if len(sin_match) > 10:
        ejemplos += f"; +{len(sin_match) - 10} más"
    try:
        await notificaciones_service.crear(
            db, _RESOLVER_ACTOR,
            {
                "titulo": f"{len(sin_match)} localidad(es) sin resolver — {origen_label}",
                "mensaje": (
                    f"El resolver de localidades (origen: {origen_label}) no pudo "
                    f"matchear contra el padrón oficial: {ejemplos}"
                ),
                "nivel": "advertencia",
                "origen": "geo_resolver",
                "enlace": ENLACE_PENDIENTES,
                "destino_tipo": "rol",
                "destino_valor": "Admin",
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "No se pudo crear la notificación de localidades sin resolver (origen=%s)",
            origen_label,
        )


async def resolver_lote(
    db: AsyncSession,
    items: list[tuple[str | None, str | None]],
    origen: str | None = None,
    cantidades: list[int | None] | None = None,
) -> list[LocalidadResuelta]:
    """Resuelve `[(departamento, localidad), ...]` en batch — una sola carga
    del padrón + alias para todo el lote (pensado para cientos de filas por
    corrida de sync, no una llamada por fila). `origen` identifica quién
    llama (ej. "cordon_cuneta", "gas_pit", "atp") — se usa sólo para logs y
    el registro de localidades sin resolver, nunca afecta el matching.
    `cantidades` (alineado con `items`) es cuántos registros de la fuente
    representa cada par, para los clientes que deduplican antes de llamar."""
    padron, por_id = await _cargar_padron(db)
    alias = await _cargar_alias(db)
    resultados = [_resolver_uno(dep, loc, padron, alias, por_id) for dep, loc in items]

    cantidades = cantidades or [None] * len(items)
    sin_match = [
        (r.departamento_in, r.localidad_in, cantidad)
        for r, cantidad in zip(resultados, cantidades)
        if r.match_tipo == "sin_match" and r.localidad_in
    ]
    if sin_match:
        logger.warning(
            "geo_resolver: %d localidad(es) sin resolver (origen=%s): %s",
            len(sin_match), origen or "desconocido", [(dep, loc) for dep, loc, _ in sin_match],
        )
        # Best-effort, en su propio SAVEPOINT: registrar el pendiente nunca debe
        # abortar el alta/edición o el sync que llamó al resolver.
        try:
            async with db.begin_nested():
                novedades = await _registrar_pendientes(db, origen, sin_match)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudieron registrar los pendientes (origen=%s)", origen or "desconocido")
            novedades = []
        if novedades:
            await _notificar_sin_match(db, origen, novedades)

    return resultados


async def resolver_uno(
    db: AsyncSession,
    departamento: str | None,
    localidad: str | None,
    origen: str | None = None,
) -> LocalidadResuelta:
    resultados = await resolver_lote(db, [(departamento, localidad)], origen=origen)
    return resultados[0]


# ── Detección de duplicados existentes (solo lectura, revisión manual) ──────

_CAMPO_POR_MODULO = {
    "cordon_cuneta": ("app.cordon_cuneta.models", "MunicipioCordonCuneta", "municipio"),
    "cordoba_hogar": ("app.cordoba_hogar.models", "LocalidadCordobaHogar", "localidad"),
    "mi_lugar": ("app.mi_lugar.models", "ProyectoML", "localidad_nombre"),
}


async def detectar_duplicados(db: AsyncSession, modulo: str) -> list[dict]:
    """Agrupa las filas activas de `modulo` por nombre normalizado y devuelve
    sólo los grupos con más de una grafía cruda distinta — para revisión
    manual (§4.4). No fusiona ni borra nada."""
    import importlib

    modulo_path, clase_nombre, campo_nombre = _CAMPO_POR_MODULO[modulo]
    mod = importlib.import_module(modulo_path)
    clase = getattr(mod, clase_nombre)
    campo = getattr(clase, campo_nombre)

    rows = (
        await db.execute(select(campo).where(clase.deleted_at.is_(None)))
    ).scalars().all()

    grupos: dict[str, dict[str, int]] = {}
    for texto in rows:
        if not texto:
            continue
        norm = normalize_name(texto)
        conteo = grupos.setdefault(norm, {})
        conteo[texto] = conteo.get(texto, 0) + 1

    return [
        {
            "normalizado": norm,
            "variantes": [
                {"texto": t, "cantidad_filas": c}
                for t, c in sorted(variantes.items())
            ],
        }
        for norm, variantes in sorted(grupos.items())
        if len(variantes) > 1
    ]
