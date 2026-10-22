"""Padrón político único (ADR-027, docs/files/spec-padron-politico-gobierno-privada.md).

Intendente y partido de cada localidad salen del padrón de Gobierno (svc-datos-externos), y del
de Privada donde Gobierno no tiene dato. Dos operaciones:

- `listar`: lo que Privada tiene hoy y su respaldo, para que svc-datos-externos arme el cruce y
  complete lo que le falte.
- `sincronizar`: trae el combinado y lo escribe en `priv_localidades_info`, guardando antes el
  valor original de cada fila en `priv_localidades_info_respaldo` (una vez, nunca se pisa).

Los logs llevan conteos, nunca nombres.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AuthUser
from app.common import norm, now_utc
from app.integrations.datos_externos import fetch_padron_combinado
from app.territorial.models import GeoLocalidad, LocalidadInfo, LocalidadInfoRespaldo

logger = logging.getLogger(__name__)

_CAMPOS = (("intendente", "intendente_jefe_comunal"), ("partido", "partido_politico"))


async def listar(db: AsyncSession) -> list[dict]:
    respaldo = {
        (r.departamento, r.localidad): r for r in (await db.execute(select(LocalidadInfoRespaldo))).scalars()
    }
    out = []
    for f in (await db.execute(select(LocalidadInfo).order_by(LocalidadInfo.departamento, LocalidadInfo.localidad))).scalars():
        r = respaldo.get((f.departamento, f.localidad))
        out.append({
            "departamento": f.departamento,
            "localidad": f.localidad,
            "id_geo": f.id_geo,
            "intendente": f.intendente_jefe_comunal,
            "partido": f.partido_politico,
            "respaldado": r is not None,
            "intendente_respaldo": r.intendente_jefe_comunal if r else f.intendente_jefe_comunal,
            "partido_respaldo": r.partido_politico if r else f.partido_politico,
        })
    return out


def _respaldar(db: AsyncSession, fila: LocalidadInfo, respaldadas: set[tuple[str, str]]) -> None:
    clave = (fila.departamento, fila.localidad)
    if clave in respaldadas:
        return
    db.add(LocalidadInfoRespaldo(
        departamento=fila.departamento,
        localidad=fila.localidad,
        id_geo=fila.id_geo,
        intendente_jefe_comunal=fila.intendente_jefe_comunal,
        partido_politico=fila.partido_politico,
        respaldado_en=now_utc(),
    ))
    respaldadas.add(clave)


async def sincronizar(db: AsyncSession, actor: AuthUser, dry_run: bool = False) -> dict:
    """Escribe el padrón combinado en `priv_localidades_info` (spec §2). Lanza
    `PadronPoliticoNoDisponible` sin tocar nada si svc-datos-externos no responde."""
    combinado = {str(f["id_geo"]): f for f in await fetch_padron_combinado() if f.get("id_geo")}
    filas = list((await db.execute(select(LocalidadInfo))).scalars())
    por_id: dict[str, list[LocalidadInfo]] = {}
    for f in filas:
        if f.id_geo:
            por_id.setdefault(f.id_geo, []).append(f)
    por_clave = {(norm(f.departamento), norm(f.localidad)): f for f in filas}
    respaldadas = {
        (r.departamento, r.localidad)
        for r in (await db.execute(select(LocalidadInfoRespaldo.departamento, LocalidadInfoRespaldo.localidad))).all()
    }
    espejo = {g.id_geo: g for g in (await db.execute(select(GeoLocalidad))).scalars()}

    ahora = now_utc()
    actualizadas = creadas = campos_cambiados = 0
    sin_espejo: list[str] = []
    for id_geo, c in combinado.items():
        destino = por_id.get(id_geo)
        nueva = False
        if not destino:
            geo = espejo.get(id_geo)
            if geo is None:
                sin_espejo.append(id_geo)
                continue
            existente = por_clave.get((norm(geo.departamento), norm(geo.localidad)))
            if existente is not None:  # misma localidad cargada sin `id_geo`
                destino = [existente]
                if not dry_run:
                    existente.id_geo = id_geo
            else:
                nueva = True
                creadas += 1
                if dry_run:
                    continue
                fila = LocalidadInfo(
                    departamento=geo.departamento, localidad=geo.localidad, id_geo=id_geo,
                    created_at=ahora, created_by=actor.email, updated_at=ahora, updated_by=actor.email,
                )
                db.add(fila)
                destino = [fila]
        for fila in destino:
            cambios = {
                col: c[campo] for campo, col in _CAMPOS
                if c.get(campo) and getattr(fila, col) != c[campo]
            }
            if not cambios:
                continue
            campos_cambiados += len(cambios)
            actualizadas += not nueva
            if dry_run:
                continue
            if not nueva:
                _respaldar(db, fila, respaldadas)
            for col, valor in cambios.items():
                setattr(fila, col, valor)
            fila.updated_at = ahora
            fila.updated_by = actor.email
            await audit.log_audit(
                db, actor=actor, action="CREATE" if nueva else "UPDATE", resource_type="privada_localidad_info",
                resource_id=f"{norm(fila.departamento)}|{norm(fila.localidad)}",
                payload={"origen": "padron_politico_gobierno", "campos": sorted(cambios)},
            )
    if not dry_run:
        await db.flush()
    sin_par = sum(1 for f in filas if not f.id_geo or f.id_geo not in combinado)
    resumen = {
        "dry_run": dry_run,
        "localidades_gobierno": len(combinado),
        "filas_privada": len(filas),
        "filas_actualizadas": actualizadas,
        "filas_creadas": creadas,
        "campos_cambiados": campos_cambiados,
        "filas_privada_sin_par_en_gobierno": sin_par,
        "id_geo_sin_espejo": sin_espejo,
    }
    logger.info("padrón político: %s", {k: v for k, v in resumen.items() if k != "id_geo_sin_espejo"})
    return resumen
