"""Rollup territorial para federación server-side hacia `resumen_territorial`
de svc-vivienda (ADR-025, mismo patrón que ADR-016/021/022).

Consumido únicamente por `GET /internal/datos-externos/rollup-territorial` —
nunca por el frontend. Devuelve, por `id_geo`, población/viviendas del Censo
2022 y transferencias del último período cargado (total + desglose por
concepto) — mismo espíritu de rollup acotado que ya usan
Privada/Gasífera/Gralgob (no expone todo el modelo interno).

Desde la Fase 1 del Tablero de Gobierno
(spec-datos-externos-fase1-nomenclador-demografia.md §6) suma, de forma
aditiva, `superficie_km2` y `poblacion_2010` (públicos) y el objeto
`ficha_gobierno` (restringido: svc-vivienda sólo lo entrega a los roles
`Admin` y `Autoridad`). La población expuesta sigue siendo la del Censo.

Itera sobre la UNIÓN de `id_geo`s presentes en Censo o en Transferencias, no
sólo sobre Censo — bug real encontrado en producción (2026-10-01, 34
localidades con transferencias bien matcheadas, incluida "Agua de Oro",
desaparecían del rollup porque su fila de Censo había quedado ambigua/sin
`id_geo` — el Censo "Cuadro 1.6" no trae departamento, así que dos
localidades homónimas en departamentos distintos, como las dos "Agua de
Oro" de Colón y Río Segundo, no se pueden desambiguar sólo con el nombre).
"""
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.fuentes_oficiales.models import (
    ExtEquipamiento,
    ExtEstadisticaVital,
    ExtEstDepartamento,
    ExtEstGobiernoLocal,
    ExtRenabapBarrio,
)
from app.geo_censo.models import ExtGeoCenso
from app.gobierno.models import CAMPOS_RESTRINGIDOS, ExtGobEnte, ExtGobLocalidad
from app.transferencias.models import ExtTransferencia

_TIPO_A_CATEGORIA = {"municipio": "MU", "comuna": "CO"}


def _as_float(v: Any) -> float | None:
    return float(v) if v is not None else None


async def _ultimo_periodo(db: AsyncSession) -> Any:
    return (await db.execute(select(func.max(ExtTransferencia.periodo)))).scalar_one_or_none()


def _ficha_gobierno(loc: ExtGobLocalidad | None) -> dict | None:
    if loc is None:
        return None
    ficha = {campo: getattr(loc, campo) for campo in CAMPOS_RESTRINGIDOS}
    ficha["masa_salarial"] = _as_float(ficha["masa_salarial"])
    return ficha if any(v is not None for v in ficha.values()) else None


async def zonas_rurales(db: AsyncSession) -> list[dict]:
    """Población sin gobierno local por departamento. Si hay datos de
    Estadística (spec-datos-externos-fuentes-oficiales.md §6), es el dato
    oficial del Censo (departamento − Σ gobiernos locales); si no, la
    estimación de Gobierno. El nombre del departamento sale siempre del
    nomenclador de Gobierno (misma grafía que hoy consume svc-vivienda)."""
    deptos = (await db.execute(select(ExtEstDepartamento))).scalars().all()
    if deptos:
        nombres = {
            r.codigo_dpto_indec: r.departamento_gob
            for r in (await db.execute(
                select(ExtGobLocalidad.codigo_dpto_indec, ExtGobLocalidad.departamento_gob)
                .where(ExtGobLocalidad.deleted_at.is_(None))
            )).all()
        }
        return [
            {
                "departamento": nombres.get(d.codigo_dpto_indec) or d.nombre,
                "poblacion_2022": d.poblacion_fuera_gl_2022,
                "poblacion_2010": d.poblacion_fuera_gl_2010,
                "fuente": "censo",
            }
            for d in sorted(deptos, key=lambda d: nombres.get(d.codigo_dpto_indec) or d.nombre or "")
        ]

    rows = (
        await db.execute(
            select(ExtGobEnte.departamento, ExtGobEnte.poblacion_2022, ExtGobEnte.poblacion_2010)
            .where(ExtGobEnte.tipo_ente == "zona_rural", ExtGobEnte.deleted_at.is_(None))
            .order_by(ExtGobEnte.departamento)
        )
    ).all()
    return [
        {
            "departamento": r.departamento, "poblacion_2022": r.poblacion_2022,
            "poblacion_2010": r.poblacion_2010, "fuente": "gobierno_estimacion",
        }
        for r in rows
    ]


def _suma(*valores: float | None) -> float | None:
    presentes = [v for v in valores if v is not None]
    return round(sum(presentes), 4) if presentes else None


async def _indicadores_por_codigo(db: AsyncSession) -> dict[str, dict]:
    """Subconjunto federado de las fuentes oficiales, por código INDEC
    (spec-datos-externos-fuentes-oficiales.md §6). Datos públicos."""
    resultado: dict[str, dict] = {}
    for g in (await db.execute(select(ExtEstGobiernoLocal))).scalars().all():
        resultado[g.codigo_indec] = {
            "anio_censo": 2022,
            "nbi_pct": g.nbi_pct,
            "gas_red_pct": g.gas_red_pct,
            "agua_red_pct": g.agua_red_pct,
            "cloacas_pct": g.cloacas_pct,
            "internet_pct": g.internet_pct,
            "inquilinos_pct": g.inquilinos_pct,
            "nbi_hacinamiento_pct": g.nbi_hacinamiento_pct,
            "calidad_iii_iv_pct": _suma(g.calidad_iii_pct, g.calidad_iv_pct),
            "hogares_hacinamiento": g.hogares_hacinamiento,
            "hogares_calidad_iv": g.hogares_calidad_iv,
            "desocupacion_pct": g.desocupacion_pct,
            "cobertura_salud_pct": g.cobertura_salud_pct,
            "secundario_completo_pct": g.secundario_completo_pct,
            "ips_valor": g.ips_valor,
            "ips_nivel": g.ips_nivel,
            "renabap_barrios": 0,
            "renabap_familias": 0,
            "establecimientos_salud": 0,
            "establecimientos_educativos": 0,
            "vitales_anio": None,
            "nacimientos": None,
            "defunciones": None,
        }
    if not resultado:
        return resultado

    for r in (await db.execute(
        select(ExtRenabapBarrio.codigo_indec, func.count(), func.sum(ExtRenabapBarrio.familias))
        .where(ExtRenabapBarrio.codigo_indec.is_not(None)).group_by(ExtRenabapBarrio.codigo_indec)
    )).all():
        if r[0] in resultado:
            resultado[r[0]]["renabap_barrios"] = r[1]
            resultado[r[0]]["renabap_familias"] = int(r[2] or 0)

    clave_tipo = {"salud": "establecimientos_salud", "educacion": "establecimientos_educativos"}
    for r in (await db.execute(
        select(ExtEquipamiento.codigo_indec, ExtEquipamiento.tipo, func.count())
        .where(ExtEquipamiento.codigo_indec.is_not(None)).group_by(ExtEquipamiento.codigo_indec, ExtEquipamiento.tipo)
    )).all():
        if r[0] in resultado and r[1] in clave_tipo:
            resultado[r[0]][clave_tipo[r[1]]] = r[2]

    ultimo_anio = (await db.execute(select(func.max(ExtEstadisticaVital.anio)))).scalar_one_or_none()
    if ultimo_anio is not None:
        for r in (await db.execute(
            select(ExtEstadisticaVital.codigo_indec, ExtEstadisticaVital.tipo, func.sum(ExtEstadisticaVital.total))
            .where(ExtEstadisticaVital.anio == ultimo_anio, ExtEstadisticaVital.codigo_indec.is_not(None))
            .group_by(ExtEstadisticaVital.codigo_indec, ExtEstadisticaVital.tipo)
        )).all():
            if r[0] in resultado and r[1] in ("nacimientos", "defunciones"):
                resultado[r[0]]["vitales_anio"] = ultimo_anio
                resultado[r[0]][r[1]] = int(r[2] or 0)
    return resultado


async def rollup_territorial(db: AsyncSession) -> list[dict]:
    censo_rows = (
        await db.execute(
            select(
                ExtGeoCenso.id_geo,
                ExtGeoCenso.codigo_indec,
                ExtGeoCenso.categoria,
                ExtGeoCenso.poblacion_2022,
                ExtGeoCenso.viviendas_2022,
            ).where(ExtGeoCenso.id_geo.is_not(None), ExtGeoCenso.deleted_at.is_(None))
        )
    ).all()
    censo_por_id_geo = {c.id_geo: c for c in censo_rows}

    gob_rows = (
        await db.execute(
            select(ExtGobLocalidad).where(ExtGobLocalidad.id_geo.is_not(None), ExtGobLocalidad.deleted_at.is_(None))
        )
    ).scalars().all()
    gob_por_id_geo: dict[str, ExtGobLocalidad] = {}
    for g in gob_rows:
        gob_por_id_geo.setdefault(g.id_geo, g)

    ultimo_periodo = await _ultimo_periodo(db)
    transferencias_por_id_geo: dict[str, dict] = {}
    metadata_por_id_geo: dict[str, dict] = {}
    if ultimo_periodo is not None:
        tr_rows = (
            await db.execute(
                select(
                    ExtTransferencia.id_geo,
                    ExtTransferencia.concepto,
                    func.sum(ExtTransferencia.monto).label("monto_sum"),
                )
                .where(ExtTransferencia.periodo == ultimo_periodo, ExtTransferencia.id_geo.is_not(None))
                .group_by(ExtTransferencia.id_geo, ExtTransferencia.concepto)
            )
        ).all()
        for r in tr_rows:
            entry = transferencias_por_id_geo.setdefault(r.id_geo, {"por_concepto": {}, "total": 0.0})
            monto = _as_float(r.monto_sum) or 0.0
            entry["por_concepto"][r.concepto] = monto
            if r.concepto != "total":
                entry["total"] += monto

        # codigo_indec/tipo sólo hacen falta para id_geo que NO tienen fila de
        # censo (si la tienen, esos campos ya vienen de ahí) — consulta aparte
        # para no repetir columnas funcionalmente dependientes en el group_by
        # de arriba.
        # Sin DISTINCT ON (no portable a SQLite, que usan los tests) — se trae
        # todo (6 filas por id_geo como mucho, un concepto por fila) y se
        # dedupea en Python, quedándose con la primera que aparece.
        faltantes = [id_geo for id_geo in transferencias_por_id_geo if id_geo not in censo_por_id_geo]
        if faltantes:
            meta_rows = (
                await db.execute(
                    select(ExtTransferencia.id_geo, ExtTransferencia.codigo_indec, ExtTransferencia.tipo)
                    .where(ExtTransferencia.periodo == ultimo_periodo, ExtTransferencia.id_geo.in_(faltantes))
                )
            ).all()
            for r in meta_rows:
                metadata_por_id_geo.setdefault(r.id_geo, {"codigo_indec": r.codigo_indec, "tipo": r.tipo})

    indicadores_por_codigo = await _indicadores_por_codigo(db)

    resultado = []
    for id_geo in censo_por_id_geo.keys() | transferencias_por_id_geo.keys() | gob_por_id_geo.keys():
        c = censo_por_id_geo.get(id_geo)
        g = gob_por_id_geo.get(id_geo)
        tr = transferencias_por_id_geo.get(id_geo)
        meta = metadata_por_id_geo.get(id_geo)
        codigo_indec = c.codigo_indec if c else (meta["codigo_indec"] if meta else (g.codigo_indec if g else None))
        resultado.append({
            "id_geo": id_geo,
            "codigo_indec": codigo_indec,
            "categoria": c.categoria if c else (_TIPO_A_CATEGORIA.get(meta["tipo"]) if meta else (g.tipo if g else None)),
            "poblacion_2022": c.poblacion_2022 if c else None,
            "viviendas_2022": c.viviendas_2022 if c else None,
            "transferencias_periodo": ultimo_periodo.isoformat() if ultimo_periodo else None,
            "transferencias_total": tr["total"] if tr else None,
            "transferencias_por_concepto": tr["por_concepto"] if tr else None,
            "superficie_km2": _as_float(g.superficie_km2) if g else None,
            "poblacion_2010": g.poblacion_2010 if g else None,
            "ficha_gobierno": _ficha_gobierno(g),
            # Fuentes oficiales públicas (spec-datos-externos-fuentes-oficiales.md §6).
            "indicadores": indicadores_por_codigo.get(codigo_indec) if codigo_indec else None,
        })
    return resultado
