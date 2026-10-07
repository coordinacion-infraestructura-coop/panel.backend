"""Padrón oficial de localidades en svc-privada (ADR-026,
docs/files/spec-privada-padron-oficial.md).

`priv_geo_localidades` es un espejo de solo lectura de `viv_geo_localidades`
(svc-vivienda): mismos `id_geo`, mismos nombres, mismo `activo`. Este módulo
tiene las dos operaciones que lo sostienen:

- `sync_padron`: trae el padrón oficial y actualiza el espejo.
- `normalizar_gestiones`: repunta en lote las gestiones (y
  `priv_localidades_info`) al `id_geo` y nombre oficiales.

Ninguna de las dos sigue adelante si svc-vivienda no responde
(`PadronNoDisponible`): "no pude leer el padrón" nunca se trata como "ninguna
localidad matchea".
"""
import logging
from collections import Counter

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AuthUser
from app.common import now_utc
from app.gestiones.models import Gestion, GestionEvento
from app.integrations import geo_resolver
from app.territorial.models import GeoLocalidad, LocalidadInfo

logger = logging.getLogger(__name__)

# Queda en `priv_gestiones_eventos` como auditoría pero no en el timeline de
# Movimientos (`gestiones.service._TIPO_EVENTO_OCULTO`): es una corrección
# técnica de grafía/vínculo, no un cambio de negocio que alguien cargó.
TIPO_EVENTO = "NORMALIZACION_LOCALIDAD"

_MAX_EJEMPLOS = 50


async def sync_padron(db: AsyncSession, actor: AuthUser) -> dict:
    """Deja `priv_geo_localidades` igual al padrón oficial. Upsert por
    `id_geo`; una fila del espejo que ya no existe en el oficial se desactiva,
    nunca se borra (puede haber gestiones históricas apuntándole)."""
    oficial = {str(f["id_geo"]): f for f in await geo_resolver.fetch_padron()}
    espejo = {g.id_geo: g for g in (await db.execute(select(GeoLocalidad))).scalars().all()}

    insertadas = actualizadas = desactivadas = 0
    for id_geo, f in oficial.items():
        valores = {
            "departamento": f["departamento"],
            "localidad": f["localidad"],
            "lat": f.get("lat_centro"),
            "lon": f.get("lon_centro"),
            "activo": bool(f["activo"]),
        }
        fila = espejo.get(id_geo)
        if fila is None:
            db.add(GeoLocalidad(id_geo=id_geo, **valores))
            insertadas += 1
            continue
        cambio = False
        for campo, valor in valores.items():
            actual = getattr(fila, campo)
            if campo in ("lat", "lon"):
                igual = (actual is None and valor is None) or (
                    actual is not None and valor is not None and abs(float(actual) - float(valor)) < 1e-7
                )
            else:
                igual = actual == valor
            if not igual:
                setattr(fila, campo, valor)
                cambio = True
        actualizadas += cambio

    for id_geo, fila in espejo.items():
        if id_geo not in oficial and fila.activo:
            fila.activo = False
            desactivadas += 1

    await db.flush()
    resumen = {
        "total_oficial": len(oficial),
        "insertadas": insertadas,
        "actualizadas": actualizadas,
        "desactivadas": desactivadas,
    }
    await audit.log_audit(
        db, actor=actor, action="SYNC", resource_type="privada_padron_localidades",
        resource_id="priv_geo_localidades", payload=resumen,
    )
    logger.info("padron_sync: %s", resumen)
    return resumen


def _destino(
    geo_id: str | None,
    departamento: str,
    localidad: str,
    resuelto: str | None,
    espejo: dict[str, GeoLocalidad],
) -> tuple[str | None, str, str, str]:
    """`(geo_id, departamento, localidad, motivo)` que le corresponde a una
    gestión. Manda lo que resuelve el texto cargado; si el texto no resuelve
    pero el `geo_id` guardado es una fila activa del padrón, vale ese `geo_id`
    (ej. localidad bien elegida con el departamento mal cargado). Sin ninguna
    de las dos, queda sin vínculo y el texto no se toca."""
    fila = espejo.get(resuelto) if resuelto else None
    if fila is not None and fila.activo:
        motivo = "ya_correcta" if resuelto == geo_id else "repunteada_por_nombre"
        return fila.id_geo, fila.departamento, fila.localidad, motivo
    fila = espejo.get(geo_id) if geo_id else None
    if fila is not None and fila.activo:
        return fila.id_geo, fila.departamento, fila.localidad, "vinculo_guardado"
    return None, departamento, localidad, "sin_vinculo"


async def normalizar_gestiones(db: AsyncSession, actor: AuthUser, *, dry_run: bool = True) -> dict:
    """Repunta todas las gestiones activas al `id_geo` y nombre oficiales, y
    completa `priv_localidades_info.id_geo`. Idempotente: una segunda corrida
    no encuentra nada que cambiar. Con `dry_run` no escribe — devuelve el
    mismo resumen de lo que cambiaría.

    Presupone el espejo al día (`sync_padron`): los nombres oficiales salen de
    `priv_geo_localidades`."""
    espejo = {g.id_geo: g for g in (await db.execute(select(GeoLocalidad))).scalars().all()}

    grupos = (
        await db.execute(
            select(Gestion.geo_id, Gestion.departamento, Gestion.localidad)
            .where(Gestion.deleted_at.is_(None))
            .distinct()
        )
    ).all()
    resueltos = await geo_resolver.resolver_localidades_estricto(
        [(g.departamento, g.localidad) for g in grupos]
    )

    por_motivo: Counter[str] = Counter()
    ejemplos: dict[str, list[dict]] = {}
    modificadas = 0
    now = now_utc()
    usuario = actor.email or actor.uid or "system"

    for g, (resuelto, _tipo) in zip(grupos, resueltos):
        geo_id, departamento, localidad, motivo = _destino(g.geo_id, g.departamento, g.localidad, resuelto, espejo)
        filtro = [
            Gestion.deleted_at.is_(None),
            Gestion.departamento == g.departamento,
            Gestion.localidad == g.localidad,
            Gestion.geo_id.is_(None) if g.geo_id is None else Gestion.geo_id == g.geo_id,
        ]
        ids = (await db.execute(select(Gestion.id).where(*filtro))).scalars().all()
        cambia = (geo_id, departamento, localidad) != (g.geo_id, g.departamento, g.localidad)
        if cambia and motivo == "ya_correcta":
            motivo = "solo_grafia"  # el vínculo estaba bien, cambia sólo cómo está escrito
        por_motivo[motivo] += len(ids)

        if cambia or motivo == "sin_vinculo":
            if len(ejemplos.setdefault(motivo, [])) < _MAX_EJEMPLOS:
                ejemplos[motivo].append({
                    "gestiones": len(ids),
                    "antes": {"geo_id": g.geo_id, "departamento": g.departamento, "localidad": g.localidad},
                    "despues": {"geo_id": geo_id, "departamento": departamento, "localidad": localidad},
                })
        if not cambia:
            continue
        modificadas += len(ids)
        if dry_run:
            continue

        await db.execute(
            update(Gestion).where(*filtro).values(geo_id=geo_id, departamento=departamento, localidad=localidad)
        )
        antes = f"{g.departamento} / {g.localidad} [{g.geo_id or 'sin vínculo'}]"
        despues = f"{departamento} / {localidad} [{geo_id or 'sin vínculo'}]"
        for gestion_id in ids:
            db.add(GestionEvento(
                gestion_id=gestion_id, fecha_evento=now, usuario=usuario, rol_usuario=actor.role,
                tipo_evento=TIPO_EVENTO, campo_modificado="localidad",
                valor_anterior=antes, valor_nuevo=despues,
                comentario="Normalización contra el padrón oficial de localidades (ADR-026)",
                metadata_json={
                    "motivo": motivo,
                    "antes": {"geo_id": g.geo_id, "departamento": g.departamento, "localidad": g.localidad},
                    "despues": {"geo_id": geo_id, "departamento": departamento, "localidad": localidad},
                },
            ))

    # priv_localidades_info: sólo se completa el vínculo; la clave por texto no se toca.
    infos = (await db.execute(select(LocalidadInfo))).scalars().all()
    resueltos_info = await geo_resolver.resolver_localidades_estricto(
        [(i.departamento, i.localidad) for i in infos]
    )
    info_vinculadas = info_sin_vinculo = 0
    for info, (resuelto, _tipo) in zip(infos, resueltos_info):
        fila = espejo.get(resuelto) if resuelto else None
        id_geo = fila.id_geo if fila is not None and fila.activo else None
        if id_geo is None:
            info_sin_vinculo += 1
        if info.id_geo != id_geo:
            info_vinculadas += 1
            if not dry_run:
                info.id_geo = id_geo

    resumen = {
        "dry_run": dry_run,
        "gestiones_activas": sum(por_motivo.values()),
        "gestiones_modificadas": modificadas,
        "por_motivo": dict(por_motivo),
        "localidades_info": {
            "total": len(infos), "actualizadas": info_vinculadas, "sin_vinculo": info_sin_vinculo,
        },
        "ejemplos": ejemplos,
    }
    if not dry_run:
        await db.flush()
        await audit.log_audit(
            db, actor=actor, action="NORMALIZACION", resource_type="privada_padron_localidades",
            resource_id="priv_gestiones",
            payload={k: v for k, v in resumen.items() if k != "ejemplos"},
        )
    logger.info("normalizar_gestiones: %s", {k: v for k, v in resumen.items() if k != "ejemplos"})
    return resumen
