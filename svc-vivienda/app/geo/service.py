"""Resolución de localidades crudas contra el padrón oficial
(`viv_geo_localidades`) + la tabla de vinculación manual
(`viv_geo_alias_manual`). Único lugar de verdad para el matching — usado por
`POST /internal/geo/resolver-localidades` (llamado por Gasífera/Gralgob en
sync-time) y en proceso por `cordon_cuneta`/`cordoba_hogar` al crear/editar
(sin llamada de red, mismo servicio que el padrón).

Ver docs/files/spec-normalizacion-localidades.md §4.3/§4.9, ADR-024.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.matching import candidatos_localidad, normalize_name
from app.geo.models import GeoAliasManual, GeoLocalidad


@dataclass(frozen=True)
class LocalidadResuelta:
    departamento_in: str | None
    localidad_in: str | None
    id_geo: str | None
    departamento_oficial: str | None
    localidad_oficial: str | None
    match_tipo: str  # "manual" | "exacto" | "alias" | "sin_match"


async def _cargar_padron(db: AsyncSession) -> tuple[dict[str, list[GeoLocalidad]], dict[str, GeoLocalidad]]:
    rows = (await db.execute(select(GeoLocalidad))).scalars().all()
    por_nombre: dict[str, list[GeoLocalidad]] = {}
    por_id: dict[str, GeoLocalidad] = {}
    for g in rows:
        por_id[g.id_geo] = g
        if g.activo:
            por_nombre.setdefault(normalize_name(g.localidad), []).append(g)
    return por_nombre, por_id


async def _cargar_alias(db: AsyncSession) -> dict[str, GeoAliasManual]:
    rows = (await db.execute(select(GeoAliasManual))).scalars().all()
    return {a.texto_normalizado: a for a in rows}


def _elegir(candidatos: list[GeoLocalidad], departamento_in: str | None) -> GeoLocalidad | None:
    """Desambigua cuando el nombre normalizado matchea más de una fila del
    padrón (localidades homónimas en departamentos distintos). Nunca adivina:
    si el departamento de entrada no alcanza para desambiguar, no hay match."""
    if len(candidatos) == 1:
        return candidatos[0]
    if departamento_in:
        dep_norm = normalize_name(departamento_in)
        exactos = [g for g in candidatos if normalize_name(g.departamento) == dep_norm]
        if len(exactos) == 1:
            return exactos[0]
    return None


def _resolver_uno(
    departamento_in: str | None,
    localidad_in: str | None,
    padron: dict[str, list[GeoLocalidad]],
    alias: dict[str, GeoAliasManual],
    por_id: dict[str, GeoLocalidad],
) -> LocalidadResuelta:
    if not localidad_in:
        return LocalidadResuelta(departamento_in, localidad_in, None, None, None, "sin_match")

    loc_norm = normalize_name(localidad_in)

    a = alias.get(loc_norm)
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


async def resolver_lote(
    db: AsyncSession, items: list[tuple[str | None, str | None]]
) -> list[LocalidadResuelta]:
    """Resuelve `[(departamento, localidad), ...]` en batch — una sola carga
    del padrón + alias para todo el lote (pensado para cientos de filas por
    corrida de sync, no una llamada por fila)."""
    padron, por_id = await _cargar_padron(db)
    alias = await _cargar_alias(db)
    return [_resolver_uno(dep, loc, padron, alias, por_id) for dep, loc in items]


async def resolver_uno(db: AsyncSession, departamento: str | None, localidad: str | None) -> LocalidadResuelta:
    resultados = await resolver_lote(db, [(departamento, localidad)])
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
