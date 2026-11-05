"""Refresco de la capa semántica (spec §2.2, plan B: ETL horario).

Cada fuente se lee por separado con el rol `agente_ro`, en una transacción de solo lectura. Si una
fuente falla, sus filas del refresco anterior se conservan (se reemplaza sólo lo de las fuentes que
respondieron) y `ag_frescura` registra el error: el agente sigue respondiendo con el último dato
bueno e informa su fecha (ADR-033, Consecuencia).
"""
import logging
from datetime import date, datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import settings
from app.etl import transform as tf
from app.etl.extractores import FUENTES
from app.semantica.models import (
    AgAlias, AgAtpPago, AgFrescura, AgGestion, AgHito, AgLocalidad, AgMovimiento,
    AgProgramaItem, AgTransferencia,
)

log = logging.getLogger(__name__)

Raw = dict[str, list[dict]]
Lector = Callable[[str], Awaitable[Raw | None]]

BASES = {
    "vivienda": "db_vivienda", "privada": "db_privada", "gasifera": "db_gasifera",
    "gralgob": "db_gralgob", "datos_externos": "db_datos_externos",
}


def url_fuente(fuente: str) -> str:
    especifica = getattr(settings, f"fuente_{fuente}_url")
    if especifica:
        return especifica
    if settings.fuentes_url_plantilla:
        return settings.fuentes_url_plantilla.replace("{db}", BASES[fuente])
    return ""
_engines: dict[str, AsyncEngine] = {}


class FuenteSinConfigurar(Exception):
    pass


async def leer_fuente_postgres(fuente: str) -> Raw:
    url = url_fuente(fuente)
    if not url:
        raise FuenteSinConfigurar(fuente)
    engine = _engines.get(fuente)
    if engine is None:
        engine = _engines[fuente] = create_async_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    out: Raw = {}
    async with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SET TRANSACTION READ ONLY"))
        for nombre, sql in FUENTES[fuente].items():
            res = await conn.execute(text(sql))
            out[nombre] = [dict(r._mapping) for r in res]
        await conn.rollback()
    return out


def _ultimo(raw: Raw | None) -> datetime | None:
    if not raw or not raw.get("sync"):
        return None
    return raw["sync"][0].get("ultimo")


async def _reemplazar(db: AsyncSession, modelo, filas: list[dict], *condiciones) -> None:
    stmt = delete(modelo)
    for c in condiciones:
        stmt = stmt.where(c)
    await db.execute(stmt)
    if filas:
        await db.execute(modelo.__table__.insert(), filas)


async def refrescar(db: AsyncSession, lector: Lector = leer_fuente_postgres, hoy: date | None = None) -> dict:
    """Recarga `ag_*`. Devuelve el estado por fuente (lo mismo que queda en `ag_frescura`)."""
    hoy = hoy or date.today()
    ahora = datetime.now(timezone.utc)
    raw: dict[str, Raw | None] = {}
    estado: dict[str, dict] = {}
    for fuente in FUENTES:
        try:
            raw[fuente] = await lector(fuente)
            estado[fuente] = {"estado": "ok", "mensaje": None}
        except FuenteSinConfigurar:
            raw[fuente] = None
            estado[fuente] = {"estado": "sin_configurar", "mensaje": "URL de la fuente sin configurar"}
        except Exception as exc:  # una fuente caída no frena las demás
            log.exception("Refresco: falló la lectura de %s", fuente)
            raw[fuente] = None
            estado[fuente] = {"estado": "error", "mensaje": f"{type(exc).__name__}: {exc}"[:500]}

    viv, priv, gas, gob, ext = (raw[f] for f in ("vivienda", "privada", "gasifera", "gralgob", "datos_externos"))
    filas: dict[str, int] = {f: 0 for f in FUENTES}

    # Padrón: el de esta corrida si Vivienda respondió, si no el que ya está cargado.
    previas = {l.id_geo: {c: getattr(l, c) for c in ("poblacion", "viviendas", "intendente", "partido")}
               for l in (await db.execute(select(AgLocalidad))).scalars()}
    if viv is not None:
        locs = tf.localidades(
            viv["localidades"],
            ext["censo"] if ext is not None else None,
            priv["padron"] if priv is not None else None,
            previas,
        )
        await _reemplazar(db, AgLocalidad, locs)
        await _reemplazar(db, AgAlias, tf.alias(viv["alias"]))
        padron = tf.Padron(locs)
    else:
        padron = tf.Padron([
            {"id_geo": l.id_geo, "departamento": l.departamento, "localidad": l.localidad}
            for l in (await db.execute(select(AgLocalidad))).scalars()
        ])

    if viv is not None:
        v = tf.vivienda(viv, padron)
        progs = ("cc", "ch", "ml")
        await _reemplazar(db, AgProgramaItem, v["items"], AgProgramaItem.programa.in_(progs))
        await _reemplazar(db, AgHito, v["hitos"])
        await _reemplazar(db, AgMovimiento, v["movimientos"], AgMovimiento.programa.in_(progs))
        filas["vivienda"] = len(v["items"])

    if priv is not None:
        p = tf.privada(priv, padron, hoy)
        await _reemplazar(db, AgGestion, p["gestiones"])
        await _reemplazar(db, AgMovimiento, p["movimientos"], AgMovimiento.programa == "privada")
        filas["privada"] = len(p["gestiones"])

    if gas is not None:
        g = tf.gasifera(gas, padron)
        await _reemplazar(db, AgProgramaItem, g["items"],
                          AgProgramaItem.programa.in_(("gas_obra", "gas_accion")))
        filas["gasifera"] = len(g["items"])

    if gob is not None:
        indec = tf.indec_a_geo(ext["censo"]) if ext is not None else {}
        a = tf.gralgob(gob, padron, indec)
        await _reemplazar(db, AgProgramaItem, a["items"], AgProgramaItem.programa == "atp")
        await _reemplazar(db, AgAtpPago, a["pagos"])
        filas["gralgob"] = len(a["items"])

    if ext is not None:
        t = tf.transferencias(ext["transferencias"], padron)
        await _reemplazar(db, AgTransferencia, t)
        filas["datos_externos"] = len(t)

    for fuente, e in estado.items():
        actual = await db.get(AgFrescura, fuente)
        if e["estado"] == "ok":
            ultimo = _ultimo(raw[fuente]) or ahora
            if actual is None:
                db.add(AgFrescura(fuente=fuente, estado="ok", filas=filas[fuente],
                                  ultimo_dato=ultimo, refrescado_at=ahora))
            else:
                actual.estado, actual.filas, actual.ultimo_dato = "ok", filas[fuente], ultimo
                actual.refrescado_at, actual.mensaje = ahora, None
        else:
            # Se conserva `ultimo_dato` y `filas` del último refresco bueno.
            if actual is None:
                db.add(AgFrescura(fuente=fuente, estado=e["estado"], filas=0, ultimo_dato=None,
                                  refrescado_at=ahora, mensaje=e["mensaje"]))
            else:
                actual.estado, actual.refrescado_at, actual.mensaje = e["estado"], ahora, e["mensaje"]
        e["filas"] = filas[fuente]
    await db.flush()
    return estado
