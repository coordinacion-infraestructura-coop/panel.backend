"""Vinculación Vivienda -> Privada (ADR-020, `docs/files/spec-vinculacion-vivienda-privada.md`).

Upsert idempotente de gestiones a partir de casos de svc-vivienda (Cordón Cuneta,
Córdoba Hogar, Mi Lugar). Llamado exclusivamente desde el endpoint interno IAM-only
`POST /internal/privada/gestiones/sync` (`app/internal/router.py`) — nunca desde la UI.

Algoritmo de matching (orden estricto, corta en el primer resultado):
  0. `id_legacy` propio (ya reclamado en una sincronización anterior de este caso) —
     es lo que hace idempotente cualquier reintento o edición posterior.
  1. `nro_expediente` (si el caso lo tiene) — identidad fuerte, sin filtrar por estado.
  2. `localidad + departamento` (si no hay expediente) — sólo gestiones abiertas y sin
     `id_legacy` de otro caso (para no "robarle" el vínculo a otro caso de Vivienda).
En cualquier paso: 0 candidatos -> se crea una gestión nueva; 1 candidato -> se vincula
y se sincronizan los campos derivados; 2+ candidatos -> PENDING_REVIEW, no se toca nada
(mismo riesgo de colisión ya documentado en spec-resumen-territorial-ficha-localidad.md).
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AuthUser
from app.common import norm, now_utc
from app.gestiones.models import Gestion
from app.gestiones.service import _CERRADOS, _geo_lookup, _nuevo_evento
from app.internal.schemas import GestionSyncFromVivienda, GestionSyncResult

# Campos derivados que el sync escribe — whitelist deliberada (spec §3.5): nunca toca
# `detalle`, `observaciones`, `urgencia`, `estado` ni nada editado a mano por un
# operador de Privada. `nro_expediente` se maneja aparte (sólo si el caso lo tiene).
_CAMPOS_CATALOGO = ("categoria_id", "programa_id", "area_id", "ministerio_agencia_id", "ok_gobernador", "ok_ministro")

_ETIQUETAS_CASO = {"cc": "Cordón Cuneta", "ch": "Córdoba Hogar", "ml": "Mi Lugar"}


def _detalle_default(payload: GestionSyncFromVivienda) -> str:
    return (
        f"Caso de {_ETIQUETAS_CASO[payload.caso_tipo]} vinculado automáticamente desde "
        f"svc-vivienda (id {payload.caso_id})."
    )


async def _candidatos_por_expediente(db: AsyncSession, nro_expediente: str) -> list[Gestion]:
    return (
        await db.execute(
            select(Gestion).where(
                func.upper(func.trim(Gestion.nro_expediente)) == norm(nro_expediente),
                Gestion.deleted_at.is_(None),
            )
        )
    ).scalars().all()


async def _candidatos_por_localidad(db: AsyncSession, departamento: str, localidad: str) -> list[Gestion]:
    return (
        await db.execute(
            select(Gestion).where(
                func.upper(func.trim(Gestion.departamento)) == norm(departamento),
                func.upper(func.trim(Gestion.localidad)) == norm(localidad),
                Gestion.deleted_at.is_(None),
                Gestion.estado.notin_(_CERRADOS),
                Gestion.id_legacy.is_(None),
            )
        )
    ).scalars().all()


def _aplicar_campos(g: Gestion, payload: GestionSyncFromVivienda) -> dict[str, dict]:
    """Escribe la whitelist de campos derivados sobre `g` y devuelve el diff de lo
    que realmente cambió — es lo que alimenta la notificación de "qué se corrigió"
    y el log técnico de sync."""
    nuevos = {
        "categoria_id": payload.categoria_id,
        "programa_id": payload.programa_id,
        "area_id": payload.area_id,
        "ministerio_agencia_id": payload.ministerio_agencia_id,
        "ok_gobernador": payload.ok_gobernador,
        "ok_ministro": payload.ok_ministro,
    }
    diff: dict[str, dict] = {}
    for campo, nuevo in nuevos.items():
        anterior = getattr(g, campo)
        if (anterior or None) == (nuevo or None):
            continue
        setattr(g, campo, nuevo)
        diff[campo] = {"antes": anterior, "despues": nuevo}

    # nro_expediente: sólo se aplica si el caso de Vivienda tiene uno — nunca lo vacía
    # (el match por localidad+departamento implica que el caso no tiene expediente).
    if payload.nro_expediente:
        anterior = g.nro_expediente
        nuevo = payload.nro_expediente.strip()
        if (anterior or None) != (nuevo or None):
            g.nro_expediente = nuevo
            diff["nro_expediente"] = {"antes": anterior, "despues": nuevo}
    return diff


async def _vincular_existente(
    db: AsyncSession, actor: AuthUser, g: Gestion, payload: GestionSyncFromVivienda
) -> GestionSyncResult:
    reclamo_nuevo = g.id_legacy != payload.id_legacy
    if reclamo_nuevo:
        g.id_legacy = payload.id_legacy
    diff = _aplicar_campos(g, payload)

    if diff or reclamo_nuevo:
        g.updated_at = now_utc()
        g.updated_by = actor.email or actor.uid
        for campo, valores in diff.items():
            db.add(_nuevo_evento(
                g.id, actor, "ACTUALIZA_DATO", campo_modificado=campo,
                valor_anterior=None if valores["antes"] is None else str(valores["antes"]),
                valor_nuevo=None if valores["despues"] is None else str(valores["despues"]),
                comentario="Sincronizado desde svc-vivienda",
                metadata_json={
                    "origen": "svc-vivienda", "caso_tipo": payload.caso_tipo, "caso_id": payload.caso_id,
                },
            ))
        await db.flush()
        await audit.log_audit(
            db, actor=actor, action="SYNC_VIVIENDA", resource_type="privada_gestion",
            resource_id=g.id, payload={"campos": list(diff.keys()), "id_legacy": payload.id_legacy},
        )
    return GestionSyncResult(
        resultado="LINKED_EXISTING", id_legacy=payload.id_legacy, gestion_id=g.id, diff=diff or None,
    )


async def _crear_nueva(db: AsyncSession, actor: AuthUser, payload: GestionSyncFromVivienda) -> GestionSyncResult:
    geo = await _geo_lookup(db, payload.departamento, payload.localidad)
    if geo is None:
        return GestionSyncResult(resultado="ERROR", id_legacy=payload.id_legacy, motivo="GEO_INVALIDO")

    now = now_utc()
    new_id = str(uuid.uuid4())
    g = Gestion(
        id=new_id,
        id_legacy=payload.id_legacy,
        origen="SVC_VIVIENDA",
        estado="INGRESADO",
        fecha_ingreso=date.today(),
        fecha_estado=now,
        urgencia="Media",
        ministerio_agencia_id=payload.ministerio_agencia_id,
        detalle=payload.detalle or _detalle_default(payload),
        geo_id=geo["id_geo"],
        departamento=payload.departamento,
        localidad=payload.localidad,
        lat=geo["lat"],
        lon=geo["lon"],
        nro_expediente=payload.nro_expediente,
        categoria_id=payload.categoria_id,
        programa_id=payload.programa_id,
        area_id=payload.area_id,
        ok_gobernador=payload.ok_gobernador,
        ok_ministro=payload.ok_ministro,
        created_at=now,
        updated_at=now,
        created_by=actor.email or actor.uid,
        updated_by=actor.email or actor.uid,
    )
    db.add(g)
    db.add(_nuevo_evento(
        new_id, actor, "CREACION", estado_nuevo="INGRESADO",
        comentario="Creada automáticamente desde svc-vivienda",
        metadata_json={
            "origen": "svc-vivienda", "caso_tipo": payload.caso_tipo, "caso_id": payload.caso_id,
            "departamento": payload.departamento, "localidad": payload.localidad, "geo_id": geo["id_geo"],
        },
    ))
    await db.flush()
    await audit.log_audit(
        db, actor=actor, action="CREATE", resource_type="privada_gestion", resource_id=new_id,
        payload={"origen": "svc-vivienda", "id_legacy": payload.id_legacy},
    )
    return GestionSyncResult(resultado="LINKED_NEW", id_legacy=payload.id_legacy, gestion_id=new_id)


async def sync_gestion_from_vivienda(
    db: AsyncSession, actor: AuthUser, payload: GestionSyncFromVivienda
) -> GestionSyncResult:
    # Paso 0: ¿ya reclamamos una gestión para este caso en una sincronización anterior?
    propia = (
        await db.execute(
            select(Gestion).where(
                Gestion.id_legacy == payload.id_legacy, Gestion.deleted_at.is_(None)
            ).limit(1)
        )
    ).scalar_one_or_none()
    if propia is not None:
        return await _vincular_existente(db, actor, propia, payload)

    # Paso 1: match por expediente (identidad fuerte, sin filtrar por estado).
    if payload.nro_expediente:
        candidatos = await _candidatos_por_expediente(db, payload.nro_expediente)
        if len(candidatos) == 0:
            return await _crear_nueva(db, actor, payload)
        if len(candidatos) == 1:
            c = candidatos[0]
            if c.id_legacy is None:
                return await _vincular_existente(db, actor, c, payload)
            return GestionSyncResult(
                resultado="PENDING_REVIEW", id_legacy=payload.id_legacy,
                motivo="EXPEDIENTE_YA_VINCULADO_OTRO_CASO", candidatos=[c.id],
            )
        return GestionSyncResult(
            resultado="PENDING_REVIEW", id_legacy=payload.id_legacy,
            motivo="EXPEDIENTE_AMBIGUO", candidatos=[c.id for c in candidatos],
        )

    # Paso 2: sin expediente -> match por localidad + departamento.
    candidatos = await _candidatos_por_localidad(db, payload.departamento, payload.localidad)
    if len(candidatos) == 0:
        return await _crear_nueva(db, actor, payload)
    if len(candidatos) == 1:
        return await _vincular_existente(db, actor, candidatos[0], payload)
    return GestionSyncResult(
        resultado="PENDING_REVIEW", id_legacy=payload.id_legacy,
        motivo="LOCALIDAD_DEPARTAMENTO_AMBIGUO", candidatos=[c.id for c in candidatos],
    )
