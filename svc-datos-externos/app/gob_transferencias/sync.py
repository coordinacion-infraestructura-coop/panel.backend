"""Sincronización de solo lectura de las planillas de transferencias de Gobierno
(spec-datos-externos-fase2-transferencias.md §3).

Cada fuente se aplica sola y por reemplazo completo dentro de un SAVEPOINT: se borra la tabla y
se inserta en bloque lo que viene de la planilla, ya validado en `parse.py`. Es distinto del
SAVEPOINT por fila de la Fase 1, y a propósito: son ~60.000 filas y el reemplazo atómico evita
mezclar dos versiones de la planilla. Si una fuente falla (lectura, estructura o freno de
seguridad) su tabla queda como estaba y las demás siguen.

Solo se leen las pestañas nombradas en `FUENTES`. Las pestañas con datos políticos o
personales de esas planillas (FODEMEP: `INFORME AUGUSTO`, `Copia de RESULTADOS CALVO`;
EMPLEADOS: `Búsqueda`) nunca se piden (spec §0).

Regla de privacidad: ni `anomalias` ni los logs llevan valores de empleados o masa salarial.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_transferencias import conciliacion, parse
from app.gob_transferencias.models import (
    ExtGobCopa,
    ExtGobEmpleados,
    ExtGobFodemep,
    ExtGobFodemepEstado,
    ExtGobFofindes,
    ExtGobFommep,
)
from app.gobierno.models import ExtGobLocalidad, ExtGobSyncLog
from app.integrations import google_sheets

logger = logging.getLogger(__name__)

# Freno de seguridad (spec §3): una planilla vaciada o mal filtrada no debe borrar datos.
MIN_PROPORCION_FILAS = 0.9
MIN_LOCALIDADES = 400
_LOTE = 2000
_MAX_ANOMALIAS = 300


@dataclass(frozen=True)
class _Pestana:
    nombre: str
    parser: Callable[[list[list[Any]]], tuple[list[dict], list[dict]]]
    modelo: type


@dataclass(frozen=True)
class _Fuente:
    setting: str
    pestanas: tuple[_Pestana, ...]


FUENTES: dict[str, _Fuente] = {
    "copa": _Fuente("google_sheet_gob_copa_id", (_Pestana("COPA", parse.parsear_copa, ExtGobCopa),)),
    "fofindes": _Fuente("google_sheet_gob_fofindes_id", (_Pestana("FOFINDES", parse.parsear_fofindes, ExtGobFofindes),)),
    "fodemep": _Fuente(
        "google_sheet_gob_fodemep_id",
        (
            _Pestana("FODEMEP", parse.parsear_fodemep, ExtGobFodemep),
            _Pestana("ESTADO", parse.parsear_fodemep_estado, ExtGobFodemepEstado),
        ),
    ),
    "fommep": _Fuente("google_sheet_gob_fommep_id", (_Pestana("FROMMEP", parse.parsear_fommep, ExtGobFommep),)),
    "empleados": _Fuente("google_sheet_gob_empleados_id", (_Pestana("Activos MyC", parse.parsear_empleados, ExtGobEmpleados),)),
}

ETIQUETAS = {
    "copa": "11.1 Coparticipación (Gobierno)",
    "fofindes": "11.1 FOFINDES (Gobierno)",
    "fodemep": "11.1 FODEMEP (Gobierno)",
    "fommep": "11.1 FOMMEP (Gobierno)",
    "empleados": "13. Empleados (Gobierno)",
}

_DESCARTES = {"fila_sin_codigo", "fila_invalida", "fila_repetida"}


class SyncFallido(Exception):
    """Ninguna de las fuentes pedidas se pudo aplicar."""


class _FuenteFallida(Exception):
    pass


def _rango(pestana: str) -> str:
    return f"'{pestana}'!A1:CZ"


def _recortar(anomalias: list[dict]) -> list[dict]:
    if len(anomalias) <= _MAX_ANOMALIAS:
        return anomalias
    return anomalias[:_MAX_ANOMALIAS] + [{"tipo": "anomalias_recortadas", "total": len(anomalias)}]


async def _leer(sheet_id: str, pestana: _Pestana) -> list[list[Any]]:
    try:
        return await google_sheets.get_values(sheet_id, _rango(pestana.nombre), "UNFORMATTED_VALUE")
    except Exception as exc:  # noqa: BLE001 — cualquier falla de la fuente externa
        raise _FuenteFallida(f"no se pudo leer la pestaña {pestana.nombre}: {type(exc).__name__}") from exc


async def _reemplazar(db: AsyncSession, modelo: type, filas: list[dict]) -> None:
    async with db.begin_nested():
        await db.execute(delete(modelo))
        for i in range(0, len(filas), _LOTE):
            await db.execute(insert(modelo), filas[i : i + _LOTE])


def _frenar(pestana: str, filas: list[dict], previas: int) -> None:
    localidades = len({f["codigo_indec"] for f in filas})
    if localidades < MIN_LOCALIDADES:
        raise _FuenteFallida(
            f"la pestaña {pestana} trae {localidades} localidades (mínimo {MIN_LOCALIDADES}); no se tocó ningún dato"
        )
    if previas and len(filas) < previas * MIN_PROPORCION_FILAS:
        raise _FuenteFallida(
            f"la pestaña {pestana} trae {len(filas)} filas contra {previas} de la corrida anterior; no se tocó ningún dato"
        )


async def _aplicar(db: AsyncSession, fuente: str, codigos_nomenclador: set[str]) -> tuple[int, int, int, list[dict]]:
    """Lee, valida y reemplaza todas las pestañas de una fuente. Devuelve
    `(leidas, insertadas, descartadas, anomalias)`; lanza `_FuenteFallida` sin tocar datos."""
    definicion = FUENTES[fuente]
    sheet_id = getattr(settings, definicion.setting)
    if not sheet_id:
        raise _FuenteFallida(f"{definicion.setting.upper()} no está configurado")

    parseadas: list[tuple[_Pestana, list[dict]]] = []
    anomalias: list[dict] = []
    leidas = 0
    for pestana in definicion.pestanas:
        valores = await _leer(sheet_id, pestana)
        try:
            filas, anom = pestana.parser(valores)
        except parse.EstructuraInvalida as exc:
            raise _FuenteFallida(f"pestaña {pestana.nombre} con estructura inesperada: {exc}") from exc
        previas = (await db.execute(select(func.count()).select_from(pestana.modelo))).scalar_one()
        _frenar(pestana.nombre, filas, previas)
        leidas += max(len(valores) - 1, 0)
        anomalias.extend(anom)
        parseadas.append((pestana, filas))

    fuera = sorted({f["codigo_indec"] for _, filas in parseadas for f in filas} - codigos_nomenclador)
    anomalias.extend({"tipo": "codigo_fuera_del_nomenclador", "codigo": c} for c in fuera)

    try:
        async with db.begin_nested():
            for pestana, filas in parseadas:
                await _reemplazar(db, pestana.modelo, filas)
    except Exception as exc:  # noqa: BLE001 — el SAVEPOINT ya revirtió esta fuente
        raise _FuenteFallida(f"no se pudo guardar: {type(exc).__name__}") from exc

    insertadas = sum(len(filas) for _, filas in parseadas)
    descartadas = sum(1 for a in anomalias if a.get("tipo") in _DESCARTES)
    return leidas, insertadas, descartadas, anomalias


async def _completar_ficha_empleados(db: AsyncSession) -> None:
    """`empleados` y `masa_salarial` de la ficha restringida (Fase 1) con el último año con
    masa salarial de cada localidad."""
    filas = (
        await db.execute(
            select(ExtGobEmpleados.codigo_indec, ExtGobEmpleados.anio, ExtGobEmpleados.empleados, ExtGobEmpleados.masa_salarial)
            .where(ExtGobEmpleados.masa_salarial.is_not(None))
            .order_by(ExtGobEmpleados.anio)
        )
    ).all()
    ultimo = {c: (e, m) for c, _a, e, m in filas}  # el orden por año deja el último
    for loc in (await db.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars():
        empleados, masa = ultimo.get(loc.codigo_indec, (None, None))
        loc.empleados = empleados
        loc.masa_salarial = masa
    await db.flush()


async def _log(db: AsyncSession, fuente: str, estado: str, disparado_por: str, anomalias: list[dict], **conteos: int) -> ExtGobSyncLog:
    log = ExtGobSyncLog(
        fuente=fuente,
        estado=estado,
        anomalias=_recortar(anomalias),
        corrida_en=datetime.now(timezone.utc),
        disparado_por=disparado_por,
        filas_leidas=conteos.get("leidas", 0),
        filas_upsert=conteos.get("upsert", 0),
        filas_error=conteos.get("error", 0),
        filas_sin_match=conteos.get("sin_match", 0),
    )
    db.add(log)
    await db.flush()
    return log


async def sync_transferencias(db: AsyncSession, fuentes: list[str], disparado_por: str = "cloud-scheduler") -> list[ExtGobSyncLog]:
    """Aplica cada fuente pedida. Si fallan todas, deja los logs commiteados y lanza
    `SyncFallido` (el router devuelve 502 y `get_db` hace rollback: sin el commit explícito
    se perdería el registro de la falla)."""
    codigos = set(
        (await db.execute(select(ExtGobLocalidad.codigo_indec).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars()
    )
    logs: list[ExtGobSyncLog] = []
    for fuente in fuentes:
        try:
            leidas, insertadas, descartadas, anomalias = await _aplicar(db, fuente, codigos)
        except _FuenteFallida as exc:
            logger.warning("sync transferencias de Gobierno: %s falló: %s", fuente, exc)
            logs.append(await _log(db, fuente, "fallido", disparado_por, [{"tipo": "corrida_fallida", "detalle": str(exc)}]))
            continue
        if fuente == "empleados":
            await _completar_ficha_empleados(db)
        if fuente in conciliacion.CONCEPTO_TRANSPARENCIA:
            anomalias.extend(conciliacion.resumen_para_log(await conciliacion.calcular_transparencia(db, fuente)))
        sin_match = sum(1 for a in anomalias if a.get("tipo") == "codigo_fuera_del_nomenclador")
        logs.append(await _log(
            db, fuente, "parcial" if descartadas else "ok", disparado_por, anomalias,
            leidas=leidas, upsert=insertadas, error=descartadas, sin_match=sin_match,
        ))

    if logs and all(log.estado == "fallido" for log in logs):
        await db.commit()
        raise SyncFallido("; ".join(str((log.anomalias or [{}])[0].get("detalle")) for log in logs))
    return logs


async def get_sync_estado(db: AsyncSession) -> list[ExtGobSyncLog]:
    """Última corrida de cada fuente."""
    resultado = []
    for fuente in FUENTES:
        log = (
            await db.execute(
                select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == fuente).order_by(ExtGobSyncLog.corrida_en.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if log:
            resultado.append(log)
    return resultado


async def get_conciliacion(db: AsyncSession, anio: int | None, hoy: date | None = None) -> dict:
    return {
        "transparencia": {f: await conciliacion.calcular_transparencia(db, f, anio) for f in conciliacion.CONCEPTO_TRANSPARENCIA},
        "vista": await conciliacion.calcular_vista(db, hoy or datetime.now(timezone.utc).date()),
    }
