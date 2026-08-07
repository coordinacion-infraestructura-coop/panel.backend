import time
from datetime import datetime, time as dtime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.mi_lugar.models import (
    ConfigML,
    EstadoHistorialML,
    EstadoML,
    GeoPuntoML,
    PedidoML,
    ProyectoML,
)
from app.mi_lugar.schemas import (
    ConfigMLOut,
    ConfigMLUpdate,
    EstadoHistorialMLOut,
    EstadoMLCreate,
    EstadoMLOut,
    EstadoMLUpdate,
    GeoPuntoIn,
    GeoPuntoOut,
    PedidoMLCreate,
    PedidoMLOut,
    ProyectoMLCreate,
    ProyectoMLOut,
    ProyectoMLUpdate,
)
from app.mi_lugar.seed_data import CONFIG_SEED, ESTADOS_SEED, PROYECTOS_SEED


# ─── Estados ──────────────────────────────────────────────────────────────────

async def listar_estados_ml(db: AsyncSession, tipo: str | None = None) -> list[EstadoMLOut]:
    q = select(EstadoML)
    if tipo is not None:
        q = q.where(EstadoML.tipo == tipo)
    q = q.order_by(EstadoML.orden)
    result = await db.execute(q)
    return [EstadoMLOut.model_validate(e) for e in result.scalars().all()]


async def crear_estado_ml(db: AsyncSession, data: EstadoMLCreate, actor: AuthUser) -> EstadoMLOut:
    new_id = int(time.time() * 1000)
    estado = EstadoML(
        id=new_id,
        label=data.label,
        bg=data.bg,
        text_color=data.text_color,
        orden=data.orden,
        tipo=data.tipo,
        aplica_juridico=data.aplica_juridico,
        aplica_tecnico=data.aplica_tecnico,
        aplica_financiero=data.aplica_financiero,
    )
    db.add(estado)
    await db.flush()
    await log_audit(db, actor=actor, action="CREATE", resource_type="ml_estado",
                    resource_id=str(new_id), payload=data.model_dump())
    return EstadoMLOut.model_validate(estado)


async def actualizar_estado_ml(
    db: AsyncSession, estado_id: int, data: EstadoMLUpdate, actor: AuthUser
) -> EstadoMLOut:
    result = await db.execute(select(EstadoML).where(EstadoML.id == estado_id))
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
    await log_audit(db, actor=actor, action="UPDATE", resource_type="ml_estado",
                    resource_id=str(estado_id), payload=updates)
    return EstadoMLOut.model_validate(estado)


async def eliminar_estado_ml(db: AsyncSession, estado_id: int, actor: AuthUser) -> None:
    result = await db.execute(select(EstadoML).where(EstadoML.id == estado_id))
    estado = result.scalar_one_or_none()
    if not estado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Estado {estado_id} no encontrado"},
        )
    proy_rows = (await db.execute(
        select(ProyectoML.nombre).where(
            ProyectoML.deleted_at.is_(None),
            (ProyectoML.ejuridico == estado_id)
            | (ProyectoML.etecnico == estado_id)
            | (ProyectoML.efinanciero == estado_id)
            | (ProyectoML.estado_general == estado_id),
        )
    )).scalars().all()
    ref_hist = (await db.execute(
        select(func.count(EstadoHistorialML.id)).where(
            (EstadoHistorialML.estado_anterior_id == estado_id)
            | (EstadoHistorialML.estado_nuevo_id == estado_id)
        )
    )).scalar_one()
    if proy_rows or ref_hist > 0:
        parts = []
        if proy_rows:
            parts.append(f"proyectos: {', '.join(proy_rows)}")
        if ref_hist > 0:
            parts.append(f"{ref_hist} entrada(s) de historial")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ESTADO_EN_USO", "message": f"El estado está en uso en {' y '.join(parts)}."},
        )
    await db.delete(estado)
    await log_audit(db, actor=actor, action="DELETE", resource_type="ml_estado",
                    resource_id=str(estado_id), payload={})


# ─── Proyectos ────────────────────────────────────────────────────────────────

def _proyecto_con_geo(proy: ProyectoML, puntos: list[GeoPuntoML]) -> ProyectoMLOut:
    out = ProyectoMLOut.model_validate(proy)
    out.geo_puntos = [GeoPuntoOut.model_validate(p) for p in puntos]
    return out


async def _cargar_geo(db: AsyncSession, proyecto_id: str) -> list[GeoPuntoML]:
    result = await db.execute(
        select(GeoPuntoML)
        .where(GeoPuntoML.proyecto_id == proyecto_id)
        .order_by(GeoPuntoML.orden)
    )
    return result.scalars().all()


async def listar_proyectos_ml(
    db: AsyncSession,
    tipo: str | None = None,
    localidad_nombre: str | None = None,
    estado_id: int | None = None,
) -> list[ProyectoMLOut]:
    q = select(ProyectoML).where(ProyectoML.deleted_at.is_(None))
    if tipo:
        q = q.where(ProyectoML.tipo == tipo)
    if localidad_nombre:
        q = q.where(ProyectoML.localidad_nombre == localidad_nombre)
    if estado_id:
        q = q.where(
            (ProyectoML.ejuridico == estado_id)
            | (ProyectoML.etecnico == estado_id)
            | (ProyectoML.efinanciero == estado_id)
        )
    q = q.order_by(ProyectoML.created_at)
    proyectos = (await db.execute(q)).scalars().all()

    geo_result = await db.execute(
        select(GeoPuntoML)
        .where(GeoPuntoML.proyecto_id.in_([p.id for p in proyectos]))
        .order_by(GeoPuntoML.orden)
    )
    puntos_by_proyecto: dict[str, list[GeoPuntoML]] = {}
    for punto in geo_result.scalars().all():
        puntos_by_proyecto.setdefault(punto.proyecto_id, []).append(punto)

    return [_proyecto_con_geo(p, puntos_by_proyecto.get(p.id, [])) for p in proyectos]


async def obtener_proyecto_ml(db: AsyncSession, proyecto_id: str) -> ProyectoMLOut:
    result = await db.execute(
        select(ProyectoML).where(
            ProyectoML.id == proyecto_id,
            ProyectoML.deleted_at.is_(None),
        )
    )
    proy = result.scalar_one_or_none()
    if not proy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Proyecto {proyecto_id} no encontrado"},
        )
    puntos = await _cargar_geo(db, proyecto_id)
    return _proyecto_con_geo(proy, puntos)


async def crear_proyecto_ml(
    db: AsyncSession, data: ProyectoMLCreate, actor: AuthUser
) -> ProyectoMLOut:
    proy = ProyectoML(
        tipo=data.tipo,
        nombre=data.nombre,
        localidad_id=data.localidad_id,
        localidad_nombre=data.localidad_nombre,
        departamento=data.departamento,
        expediente=data.expediente,
        responsable=data.responsable,
        superficie=data.superficie,
        lotes=data.lotes,
        monto=data.monto,
        valor_fiscal=data.valor_fiscal,
        infra_sin_nexos=data.infra_sin_nexos,
        costo_nexos=data.costo_nexos,
        convenio_unc=data.convenio_unc,
        costo_total_infra=data.costo_total_infra,
        ok_gob=data.ok_gob,
        ejuridico=data.ejuridico,
        etecnico=data.etecnico,
        efinanciero=data.efinanciero,
        estado_general=data.estado_general,
        obs=data.obs,
        updated_by=actor.email,
    )
    db.add(proy)
    await db.flush()

    puntos = []
    for i, geo in enumerate(data.geo_puntos, start=1):
        punto = GeoPuntoML(proyecto_id=proy.id, lat=geo.lat, lng=geo.lng, orden=i)
        db.add(punto)
        puntos.append(punto)
    if puntos:
        await db.flush()

    await db.refresh(proy)
    await log_audit(db, actor=actor, action="CREATE", resource_type="ml_proyecto",
                    resource_id=proy.id, payload=data.model_dump(mode="json"))
    return _proyecto_con_geo(proy, puntos)


async def actualizar_proyecto_ml(
    db: AsyncSession, proyecto_id: str, data: ProyectoMLUpdate, actor: AuthUser
) -> ProyectoMLOut:
    result = await db.execute(
        select(ProyectoML).where(
            ProyectoML.id == proyecto_id,
            ProyectoML.deleted_at.is_(None),
        )
    )
    proy = result.scalar_one_or_none()
    if not proy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Proyecto {proyecto_id} no encontrado"},
        )

    updates = data.model_dump(exclude_unset=True)
    fecha_cambio = updates.pop("fecha_cambio", None)
    geo_puntos_data: list[GeoPuntoIn] | None = updates.pop("geo_puntos", None)

    historial = []
    for campo in ("ejuridico", "etecnico", "efinanciero"):
        if campo in updates:
            old_val = getattr(proy, campo)
            new_val = updates[campo]
            if new_val is not None and old_val != new_val:
                entry = EstadoHistorialML(
                    proyecto_id=proyecto_id,
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
        setattr(proy, key, value)

    if fecha_cambio is not None:
        proy.updated_at = datetime.combine(fecha_cambio, dtime(12, 0, 0), tzinfo=timezone.utc)

    await db.flush()

    for entry in historial:
        db.add(entry)

    puntos: list[GeoPuntoML] = []
    if geo_puntos_data is not None:
        await db.execute(
            delete(GeoPuntoML).where(GeoPuntoML.proyecto_id == proyecto_id)
        )
        for i, geo in enumerate(geo_puntos_data, start=1):
            punto = GeoPuntoML(proyecto_id=proyecto_id, lat=geo.lat, lng=geo.lng, orden=i)
            db.add(punto)
            puntos.append(punto)
    else:
        puntos = await _cargar_geo(db, proyecto_id)

    await db.flush()
    await db.refresh(proy)
    await log_audit(db, actor=actor, action="UPDATE", resource_type="ml_proyecto",
                    resource_id=proyecto_id, payload=data.model_dump(mode="json", exclude_unset=True))
    return _proyecto_con_geo(proy, puntos)


async def eliminar_proyecto_ml(db: AsyncSession, proyecto_id: str, actor: AuthUser) -> None:
    result = await db.execute(
        select(ProyectoML).where(
            ProyectoML.id == proyecto_id,
            ProyectoML.deleted_at.is_(None),
        )
    )
    proy = result.scalar_one_or_none()
    if not proy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Proyecto {proyecto_id} no encontrado"},
        )
    proy.deleted_at = datetime.now(timezone.utc)
    proy.updated_by = actor.email
    await db.flush()
    await log_audit(db, actor=actor, action="DELETE", resource_type="ml_proyecto",
                    resource_id=proyecto_id, payload={})


# ─── Historial ────────────────────────────────────────────────────────────────

async def get_historial_ml(db: AsyncSession, proyecto_id: str) -> list[EstadoHistorialMLOut]:
    result = await db.execute(
        select(EstadoHistorialML)
        .where(EstadoHistorialML.proyecto_id == proyecto_id)
        .order_by(EstadoHistorialML.created_at.desc())
    )
    return [EstadoHistorialMLOut.model_validate(h) for h in result.scalars().all()]


# ─── Pedidos ──────────────────────────────────────────────────────────────────

async def listar_pedidos_ml(
    db: AsyncSession, proyecto_id: str, actor: AuthUser
) -> list[PedidoMLOut]:
    proy = (await db.execute(
        select(ProyectoML).where(
            ProyectoML.id == proyecto_id,
            ProyectoML.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not proy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Proyecto {proyecto_id} no encontrado"},
        )
    query = select(PedidoML).where(PedidoML.proyecto_id == proyecto_id)
    actor_secs = set(actor.secretarias)
    if actor.role != "Admin" and "supervision" not in actor_secs:
        if "infraestructura" in actor_secs:
            query = query.where(
                (PedidoML.secretaria != "supervision") | PedidoML.secretaria.is_(None)
            )
        else:
            query = query.where(
                PedidoML.secretaria.not_in(["infraestructura", "supervision"])
                | PedidoML.secretaria.is_(None)
            )
    query = query.order_by(PedidoML.fecha_pedido.desc())
    result = await db.execute(query)
    return [PedidoMLOut.model_validate(p) for p in result.scalars().all()]


async def crear_pedido_ml(
    db: AsyncSession, proyecto_id: str, data: PedidoMLCreate, actor: AuthUser
) -> PedidoMLOut:
    proy = (await db.execute(
        select(ProyectoML).where(
            ProyectoML.id == proyecto_id,
            ProyectoML.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not proy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Proyecto {proyecto_id} no encontrado"},
        )
    actor_secs = set(actor.secretarias)
    secretaria = None
    if "supervision" in actor_secs:
        secretaria = "supervision"
    elif "infraestructura" in actor_secs:
        secretaria = "infraestructura"
    elif actor.secretarias:
        secretaria = actor.secretarias[0]

    pedido = PedidoML(
        proyecto_id=proyecto_id,
        descripcion=data.descripcion,
        fecha_pedido=data.fecha_pedido,
        created_by=actor.email,
        created_by_nombre=actor.nombre,
        secretaria=secretaria,
    )
    db.add(pedido)
    await db.flush()
    await log_audit(db, actor=actor, action="CREATE", resource_type="ml_pedido",
                    resource_id=pedido.id,
                    payload={"proyecto_id": proyecto_id, "fecha_pedido": str(data.fecha_pedido)})
    return PedidoMLOut.model_validate(pedido)


async def eliminar_pedido_ml(
    db: AsyncSession, proyecto_id: str, pedido_id: str, actor: AuthUser
) -> None:
    result = await db.execute(
        select(PedidoML).where(
            PedidoML.id == pedido_id,
            PedidoML.proyecto_id == proyecto_id,
        )
    )
    pedido = result.scalar_one_or_none()
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": "Pedido no encontrado"},
        )
    await db.delete(pedido)
    await log_audit(db, actor=actor, action="DELETE", resource_type="ml_pedido",
                    resource_id=pedido_id, payload={"proyecto_id": proyecto_id})


# ─── Config ───────────────────────────────────────────────────────────────────

async def obtener_config_ml(db: AsyncSession) -> ConfigMLOut:
    result = await db.execute(select(ConfigML).where(ConfigML.id == 1))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONFIG_NO_ENCONTRADA", "message": "Configuración no encontrada"},
        )
    return ConfigMLOut.model_validate(config)


async def actualizar_config_ml(
    db: AsyncSession, data: ConfigMLUpdate, actor: AuthUser
) -> ConfigMLOut:
    result = await db.execute(select(ConfigML).where(ConfigML.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = ConfigML(id=1, **CONFIG_SEED)
        db.add(config)
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(config, key, value)
    await db.flush()
    await db.refresh(config)
    await log_audit(db, actor=actor, action="UPDATE", resource_type="ml_config",
                    resource_id="1", payload={k: str(v) for k, v in updates.items()})
    return ConfigMLOut.model_validate(config)


# ─── Seed ─────────────────────────────────────────────────────────────────────

async def seed_mi_lugar(db: AsyncSession) -> None:
    count = (await db.execute(select(func.count(ProyectoML.id)))).scalar_one()
    if count > 0:
        return

    for e in ESTADOS_SEED:
        db.add(EstadoML(**e))
    await db.flush()

    config = ConfigML(id=1, **CONFIG_SEED)
    db.add(config)
    await db.flush()

    for proy_data in PROYECTOS_SEED:
        data = dict(proy_data)
        geo_puntos_data = data.pop("geo_puntos", [])
        proy = ProyectoML(**data)
        db.add(proy)
        await db.flush()
        for i, geo in enumerate(geo_puntos_data, start=1):
            db.add(GeoPuntoML(proyecto_id=proy.id, lat=geo["lat"], lng=geo["lng"], orden=i))
        await db.flush()
