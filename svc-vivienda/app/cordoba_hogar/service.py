import time
from datetime import date, datetime, time as dtime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.checklist_tecnico import estado_tecnico
from app.integrations.privada_sync import sync_gestion_privada
from app.cordoba_hogar.models import (
    ConfigCordobaHogar,
    EstadoCordobaHogar,
    EstadoHistorialCH,
    LocalidadCordobaHogar,
    PedidoCordobaHogar,
)
from app.cordoba_hogar.schemas import (
    CordobaHogarFullResponse,
    EstadoCreate,
    EstadoHistorialResponse,
    EstadoResponse,
    EstadoUpdate,
    GeoLocalidadResponse,
    LocalidadCreate,
    LocalidadResponse,
    LocalidadUpdate,
    MontoPorCasaUpdate,
    PedidoCreate,
    PedidoResponse,
    PresupuestoUpdate,
)
from app.cordoba_hogar.seed_data import ESTADOS_SEED, LOCALIDADES_SEED
from app.geo import service as geo_service
from app.geo.models import GeoLocalidad


def _localidad_response(localidad: LocalidadCordobaHogar, etecnico: int | None) -> LocalidadResponse:
    """`etecnico` no sale de la columna propia: es el estado del expediente del checklist
    (spec-estado-tecnico-desde-checklist.md §3.2)."""
    out = LocalidadResponse.model_validate(localidad)
    out.etecnico = etecnico
    return out


async def get_full(db: AsyncSession) -> CordobaHogarFullResponse:
    localidades_res = await db.execute(
        select(LocalidadCordobaHogar)
        .where(LocalidadCordobaHogar.deleted_at.is_(None))
        .order_by(LocalidadCordobaHogar.orden)
    )
    estados_res = await db.execute(select(EstadoCordobaHogar).order_by(EstadoCordobaHogar.orden))
    config_res = await db.execute(select(ConfigCordobaHogar).where(ConfigCordobaHogar.id == 1))
    config = config_res.scalar_one_or_none()
    presupuesto = float(config.presupuesto) if config else 0.0

    monto_por_casa = float(config.monto_por_casa) if config and config.monto_por_casa is not None else 34000000.0
    tecnico = await estado_tecnico.estados_expediente_por_entidad(db, "ch")

    return CordobaHogarFullResponse(
        localidades=[_localidad_response(l, tecnico.get(l.id)) for l in localidades_res.scalars().all()],
        estados=[EstadoResponse.model_validate(e) for e in estados_res.scalars().all()],
        presupuesto=presupuesto,
        monto_por_casa=monto_por_casa,
    )


async def listar_estados(db: AsyncSession) -> list[EstadoResponse]:
    result = await db.execute(select(EstadoCordobaHogar).order_by(EstadoCordobaHogar.orden))
    return [EstadoResponse.model_validate(e) for e in result.scalars().all()]


async def crear_estado(db: AsyncSession, data: EstadoCreate, actor: AuthUser) -> EstadoResponse:
    new_id = int(time.time() * 1000)
    estado = EstadoCordobaHogar(
        id=new_id,
        label=data.label,
        bg=data.bg,
        text_color=data.text_color,
        orden=data.orden,
        aplica_juridico=data.aplica_juridico,
        aplica_tecnico=data.aplica_tecnico,
        aplica_financiero=data.aplica_financiero,
    )
    db.add(estado)
    await db.flush()
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="ch_estado",
        resource_id=str(new_id), payload=data.model_dump()
    )
    return EstadoResponse.model_validate(estado)


async def actualizar_estado(
    db: AsyncSession, estado_id: int, data: EstadoUpdate, actor: AuthUser
) -> EstadoResponse:
    result = await db.execute(select(EstadoCordobaHogar).where(EstadoCordobaHogar.id == estado_id))
    estado = result.scalar_one_or_none()
    if not estado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Estado {estado_id} no encontrado"},
        )
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(estado, key, value)
    await db.flush()
    await db.refresh(estado)

    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="ch_estado",
        resource_id=str(estado_id), payload=updates
    )
    return EstadoResponse.model_validate(estado)


async def eliminar_estado(db: AsyncSession, estado_id: int, actor: AuthUser) -> None:
    result = await db.execute(select(EstadoCordobaHogar).where(EstadoCordobaHogar.id == estado_id))
    estado = result.scalar_one_or_none()
    if not estado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Estado {estado_id} no encontrado"},
        )
    # Chequea todas las FK al catálogo: dimensiones, estado_general e historial
    loc_rows = (await db.execute(
        select(LocalidadCordobaHogar.localidad).where(
            LocalidadCordobaHogar.deleted_at.is_(None),
            (LocalidadCordobaHogar.ejuridico == estado_id)
            | (LocalidadCordobaHogar.etecnico == estado_id)
            | (LocalidadCordobaHogar.efinanciero == estado_id)
            | (LocalidadCordobaHogar.estado_general == estado_id),
        )
    )).scalars().all()
    ref_hist = (await db.execute(
        select(func.count(EstadoHistorialCH.id)).where(
            (EstadoHistorialCH.estado_anterior_id == estado_id)
            | (EstadoHistorialCH.estado_nuevo_id == estado_id)
        )
    )).scalar_one()
    if loc_rows or ref_hist > 0:
        parts = []
        if loc_rows:
            parts.append(f"localidades: {', '.join(loc_rows)}")
        if ref_hist > 0:
            parts.append(f"{ref_hist} entrada(s) de historial")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ESTADO_EN_USO",
                "message": f"El estado está en uso en {' y '.join(parts)}.",
            },
        )
    await db.delete(estado)
    await log_audit(
        db, actor=actor, action="DELETE", resource_type="ch_estado",
        resource_id=str(estado_id), payload={}
    )


async def actualizar_localidad(
    db: AsyncSession, localidad_id: str, data: LocalidadUpdate, actor: AuthUser
) -> LocalidadResponse:
    result = await db.execute(
        select(LocalidadCordobaHogar).where(
            LocalidadCordobaHogar.id == localidad_id,
            LocalidadCordobaHogar.deleted_at.is_(None),
        )
    )
    localidad = result.scalar_one_or_none()
    if not localidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Localidad {localidad_id} no encontrada"},
        )

    updates = data.model_dump(exclude_unset=True)
    fecha_cambio = updates.pop("fecha_cambio", None)

    historial = []
    for campo in ("ejuridico", "efinanciero"):
        if campo in updates:
            old_val = getattr(localidad, campo)
            new_val = updates[campo]
            if new_val is not None and old_val != new_val:
                entry = EstadoHistorialCH(
                    localidad_id=localidad_id,
                    campo=campo,
                    estado_anterior_id=old_val,
                    estado_nuevo_id=new_val,
                    created_by=actor.email,
                )
                if fecha_cambio is not None:
                    entry.created_at = datetime.combine(fecha_cambio, dtime(12, 0, 0), tzinfo=timezone.utc)
                historial.append(entry)

    updates["updated_by"] = actor.email
    for key, value in updates.items():
        setattr(localidad, key, value)

    if fecha_cambio is not None:
        localidad.updated_at = datetime.combine(fecha_cambio, dtime(12, 0, 0), tzinfo=timezone.utc)

    if "localidad" in updates or "departamento" in updates:
        resuelto = await geo_service.resolver_uno(db, localidad.departamento, localidad.localidad, origen="cordoba_hogar")
        localidad.localidad_id = resuelto.id_geo
        localidad.localidad_match_tipo = resuelto.match_tipo
        # Con vínculo, lo que se guarda es el nombre del padrón oficial (ADR-026);
        # el texto que llegó sólo queda cuando la localidad no está en el padrón.
        localidad.localidad = resuelto.localidad_oficial or localidad.localidad
        localidad.departamento = resuelto.departamento_oficial or localidad.departamento

    await db.flush()

    for entry in historial:
        db.add(entry)

    await db.flush()
    await db.refresh(localidad)
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordoba_hogar",
        resource_id=localidad_id, payload=updates
    )
    await sync_gestion_privada(
        db, caso_tipo="ch", caso_id=localidad.id, nro_expediente=localidad.expediente,
        localidad=localidad.localidad, departamento=localidad.departamento, ok_gob=localidad.ok_gob,
    )
    return _localidad_response(
        localidad, await estado_tecnico.estado_expediente_de(db, "ch", localidad.id)
    )


async def _buscar_duplicado_ch(
    db: AsyncSession, localidad_raw: str, departamento_raw: str | None, id_geo: str | None
) -> LocalidadCordobaHogar | None:
    existing = (await db.execute(
        select(LocalidadCordobaHogar).where(
            func.lower(LocalidadCordobaHogar.localidad) == localidad_raw.strip().lower(),
            func.lower(LocalidadCordobaHogar.departamento) == (departamento_raw or '').strip().lower(),
            LocalidadCordobaHogar.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing is not None or not id_geo:
        return existing
    # No matcheó por texto (mayúsc/minúsc) pero sí resolvió a la misma localidad
    # oficial que un registro activo existente (ej. variante con/sin tilde) —
    # ver ADR-024/spec-normalizacion-localidades.md §4.7.
    return (await db.execute(
        select(LocalidadCordobaHogar).where(
            LocalidadCordobaHogar.localidad_id == id_geo,
            LocalidadCordobaHogar.deleted_at.is_(None),
        )
    )).scalar_one_or_none()


async def crear_localidad(
    db: AsyncSession, data: LocalidadCreate, actor: AuthUser
) -> LocalidadResponse:
    resuelto = await geo_service.resolver_uno(db, data.departamento, data.localidad, origen="cordoba_hogar")

    existing = await _buscar_duplicado_ch(db, data.localidad, data.departamento, resuelto.id_geo)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "LOCALIDAD_DUPLICADA",
                "message": f"Ya existe '{existing.localidad}' ({existing.departamento}) en el panel.",
                "existing_id": existing.id,
            },
        )

    max_orden = (await db.execute(
        select(func.max(LocalidadCordobaHogar.orden)).where(LocalidadCordobaHogar.deleted_at.is_(None))
    )).scalar_one() or 0

    localidad = LocalidadCordobaHogar(
        orden=max_orden + 1,
        localidad=resuelto.localidad_oficial or data.localidad,
        departamento=resuelto.departamento_oficial or data.departamento,
        localidad_id=resuelto.id_geo,
        localidad_match_tipo=resuelto.match_tipo,
        fecha_anuncio=data.fecha_anuncio,
        expediente=data.expediente,
        monto=data.monto,
        cantidad_casas=data.cantidad_casas,
        ok_gob=data.ok_gob,
        ejuridico=data.ejuridico,
        efinanciero=data.efinanciero,
        updated_by=actor.email,
    )
    db.add(localidad)
    try:
        await db.flush()
    except IntegrityError:
        # Doble-submit / creación concurrente: el pre-check de arriba no lo vio
        # a tiempo, pero la constraint única de DB sí lo bloqueó. Traducimos a
        # el mismo 409 legible en vez de dejar subir un 500 genérico.
        await db.rollback()
        existing = await _buscar_duplicado_ch(db, data.localidad, data.departamento, resuelto.id_geo)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "LOCALIDAD_DUPLICADA",
                "message": (
                    f"Ya existe '{existing.localidad}' ({existing.departamento}) en el panel."
                    if existing else "Ya existe una localidad con ese nombre y departamento en el panel."
                ),
                "existing_id": existing.id if existing else None,
            },
        )

    await db.refresh(localidad)
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="cordoba_hogar",
        resource_id=localidad.id, payload=data.model_dump()
    )
    await sync_gestion_privada(
        db, caso_tipo="ch", caso_id=localidad.id, nro_expediente=localidad.expediente,
        localidad=localidad.localidad, departamento=localidad.departamento, ok_gob=localidad.ok_gob,
    )
    return _localidad_response(
        localidad, await estado_tecnico.estado_expediente_de(db, "ch", localidad.id)
    )


async def eliminar_localidad(db: AsyncSession, localidad_id: str, actor: AuthUser) -> None:
    result = await db.execute(
        select(LocalidadCordobaHogar).where(
            LocalidadCordobaHogar.id == localidad_id,
            LocalidadCordobaHogar.deleted_at.is_(None),
        )
    )
    localidad = result.scalar_one_or_none()
    if not localidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Localidad {localidad_id} no encontrada"},
        )
    localidad.deleted_at = datetime.now(timezone.utc)
    localidad.updated_by = actor.email
    await db.flush()
    await log_audit(
        db, actor=actor, action="DELETE", resource_type="cordoba_hogar",
        resource_id=localidad_id, payload={}
    )


async def get_historial(
    db: AsyncSession, localidad_id: str
) -> list[EstadoHistorialResponse]:
    result = await db.execute(
        select(EstadoHistorialCH)
        .where(EstadoHistorialCH.localidad_id == localidad_id)
    )
    entradas = [EstadoHistorialResponse.model_validate(h) for h in result.scalars().all()]
    # El Técnico se cambia desde el checklist: su historial vive en viv_checklist_estado_hist.
    entradas += [
        EstadoHistorialResponse(localidad_id=localidad_id, **h)
        for h in await estado_tecnico.historial_tecnico(db, "ch", localidad_id)
    ]
    entradas.sort(key=lambda h: estado_tecnico.orden_cronologico(h.created_at), reverse=True)
    return entradas


async def listar_geo_localidades(db: AsyncSession) -> list[GeoLocalidadResponse]:
    result = await db.execute(
        select(GeoLocalidad)
        .where(GeoLocalidad.activo.is_(True))
        .order_by(GeoLocalidad.departamento, GeoLocalidad.localidad)
    )
    return [GeoLocalidadResponse.model_validate(g) for g in result.scalars().all()]


async def actualizar_presupuesto(
    db: AsyncSession, data: PresupuestoUpdate, actor: AuthUser
) -> float:
    result = await db.execute(select(ConfigCordobaHogar).where(ConfigCordobaHogar.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = ConfigCordobaHogar(id=1, presupuesto=data.presupuesto)
        db.add(config)
    else:
        config.presupuesto = data.presupuesto
    await db.flush()
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordoba_hogar_config",
        resource_id="presupuesto", payload={"presupuesto": str(data.presupuesto)}
    )
    return float(config.presupuesto)


async def actualizar_monto_por_casa(
    db: AsyncSession, data: MontoPorCasaUpdate, actor: AuthUser
) -> float:
    result = await db.execute(select(ConfigCordobaHogar).where(ConfigCordobaHogar.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = ConfigCordobaHogar(id=1, presupuesto=0, monto_por_casa=data.monto_por_casa)
        db.add(config)
    else:
        config.monto_por_casa = data.monto_por_casa
    await db.flush()
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordoba_hogar_config",
        resource_id="monto_por_casa", payload={"monto_por_casa": str(data.monto_por_casa)}
    )
    return float(config.monto_por_casa)


async def listar_pedidos(db: AsyncSession, localidad_id: str, actor: AuthUser) -> list[PedidoResponse]:
    localidad = (await db.execute(
        select(LocalidadCordobaHogar).where(
            LocalidadCordobaHogar.id == localidad_id,
            LocalidadCordobaHogar.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not localidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Localidad {localidad_id} no encontrada"},
        )
    query = (
        select(PedidoCordobaHogar)
        .where(PedidoCordobaHogar.localidad_id == localidad_id)
    )
    actor_secs = set(actor.secretarias)
    if actor.role != "Admin" and "supervision" not in actor_secs:
        if "infraestructura" in actor_secs:
            query = query.where(
                (PedidoCordobaHogar.secretaria != "supervision")
                | PedidoCordobaHogar.secretaria.is_(None)
            )
        else:
            query = query.where(
                PedidoCordobaHogar.secretaria.not_in(["infraestructura", "supervision"])
                | PedidoCordobaHogar.secretaria.is_(None)
            )
    query = query.order_by(PedidoCordobaHogar.fecha_pedido.desc())
    result = await db.execute(query)
    return [PedidoResponse.model_validate(p) for p in result.scalars().all()]


async def crear_pedido(
    db: AsyncSession, localidad_id: str, data: PedidoCreate, actor: AuthUser
) -> PedidoResponse:
    localidad = (await db.execute(
        select(LocalidadCordobaHogar).where(
            LocalidadCordobaHogar.id == localidad_id,
            LocalidadCordobaHogar.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not localidad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Localidad {localidad_id} no encontrada"},
        )
    actor_secs = set(actor.secretarias)
    secretaria = None
    if "supervision" in actor_secs:
        secretaria = "supervision"
    elif "infraestructura" in actor_secs:
        secretaria = "infraestructura"
    elif actor.secretarias:
        secretaria = actor.secretarias[0]

    pedido = PedidoCordobaHogar(
        localidad_id=localidad_id,
        descripcion=data.descripcion,
        fecha_pedido=data.fecha_pedido,
        created_by=actor.email,
        created_by_nombre=actor.nombre,
        secretaria=secretaria,
    )
    db.add(pedido)
    await db.flush()
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="ch_pedido",
        resource_id=pedido.id, payload={"localidad_id": localidad_id, "fecha_pedido": str(data.fecha_pedido)}
    )
    return PedidoResponse.model_validate(pedido)


async def delete_pedido(
    db: AsyncSession, localidad_id: str, pedido_id: str, actor: AuthUser
) -> None:
    result = await db.execute(
        select(PedidoCordobaHogar).where(
            PedidoCordobaHogar.id == pedido_id,
            PedidoCordobaHogar.localidad_id == localidad_id,
        )
    )
    pedido = result.scalar_one_or_none()
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": "Pedido no encontrado"},
        )
    await db.delete(pedido)
    await log_audit(
        db, actor=actor, action="DELETE", resource_type="ch_pedido",
        resource_id=pedido_id, payload={"localidad_id": localidad_id}
    )


async def seed_cordoba_hogar(db: AsyncSession) -> None:
    count = (await db.execute(select(func.count(LocalidadCordobaHogar.id)))).scalar_one()
    if count > 0:
        return

    for e in ESTADOS_SEED:
        db.add(EstadoCordobaHogar(**e))
    await db.flush()

    for loc in LOCALIDADES_SEED:
        loc_data = dict(loc)
        if loc_data.get("fecha_anuncio"):
            loc_data["fecha_anuncio"] = date.fromisoformat(loc_data["fecha_anuncio"])
        db.add(LocalidadCordobaHogar(**loc_data))
    await db.flush()

    config = ConfigCordobaHogar(id=1, presupuesto=0)
    db.add(config)
    await db.flush()
