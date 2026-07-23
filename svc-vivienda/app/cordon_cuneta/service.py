import time
import uuid
from datetime import datetime, time as dtime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.cordon_cuneta.models import (
    ConfigCordonCuneta,
    EstadoCordonCuneta,
    EstadoHistorialCC,
    MunicipioCordonCuneta,
    PedidoCordonCuneta,
)
from app.cordon_cuneta.schemas import (
    CordonCunetaFullResponse,
    EstadoCreate,
    EstadoHistorialResponse,
    EstadoResponse,
    EstadoUpdate,
    GeoLocalidadResponse,
    MunicipioCreate,
    MunicipioResponse,
    MunicipioUpdate,
    PedidoCreate,
    PedidoResponse,
    PresupuestoUpdate,
)
from app.cordon_cuneta.seed_data import ESTADOS_SEED, MUNICIPIOS_SEED
from app.geo.models import GeoLocalidad


async def _compute_estado_general(db: AsyncSession, ids: list[int | None]) -> int | None:
    non_null = [i for i in ids if i is not None]
    if not non_null:
        return None
    result = await db.execute(
        select(EstadoCordonCuneta.id)
        .where(EstadoCordonCuneta.id.in_(non_null))
        .order_by(EstadoCordonCuneta.orden.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _recompute_all_estado_general(db: AsyncSession) -> None:
    """Recalcula estado_general de todos los municipios activos.

    Necesario cuando cambia el `orden` de un estado del catálogo: el
    estado_general de cualquier municipio que use ese catálogo puede
    quedar desactualizado aunque sus dimensiones no hayan cambiado.
    Se recorre toda la tabla (decenas de filas) en vez de calcular el
    subconjunto afectado — más simple y suficientemente barato a esta escala.
    """
    result = await db.execute(
        select(MunicipioCordonCuneta).where(MunicipioCordonCuneta.deleted_at.is_(None))
    )
    for municipio in result.scalars().all():
        municipio.estado_general = await _compute_estado_general(
            db, [municipio.ejuridico, municipio.etecnico, municipio.efinanciero]
        )
    await db.flush()


async def get_full(db: AsyncSession) -> CordonCunetaFullResponse:
    municipios_res = await db.execute(
        select(MunicipioCordonCuneta)
        .where(MunicipioCordonCuneta.deleted_at.is_(None))
        .order_by(MunicipioCordonCuneta.orden)
    )
    estados_res = await db.execute(select(EstadoCordonCuneta).order_by(EstadoCordonCuneta.orden))
    config_res = await db.execute(select(ConfigCordonCuneta).where(ConfigCordonCuneta.id == 1))
    config = config_res.scalar_one_or_none()
    presupuesto = float(config.presupuesto) if config else 0.0

    return CordonCunetaFullResponse(
        municipios=[MunicipioResponse.model_validate(m) for m in municipios_res.scalars().all()],
        estados=[EstadoResponse.model_validate(e) for e in estados_res.scalars().all()],
        presupuesto=presupuesto,
    )


async def listar_estados(db: AsyncSession) -> list[EstadoResponse]:
    result = await db.execute(select(EstadoCordonCuneta).order_by(EstadoCordonCuneta.orden))
    return [EstadoResponse.model_validate(e) for e in result.scalars().all()]


async def crear_estado(db: AsyncSession, data: EstadoCreate, actor: AuthUser) -> EstadoResponse:
    new_id = int(time.time() * 1000)
    estado = EstadoCordonCuneta(
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
        db, actor=actor, action="CREATE", resource_type="cc_estado",
        resource_id=str(new_id), payload=data.model_dump()
    )
    return EstadoResponse.model_validate(estado)


async def actualizar_estado(
    db: AsyncSession, estado_id: int, data: EstadoUpdate, actor: AuthUser
) -> EstadoResponse:
    result = await db.execute(select(EstadoCordonCuneta).where(EstadoCordonCuneta.id == estado_id))
    estado = result.scalar_one_or_none()
    if not estado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Estado {estado_id} no encontrado"},
        )
    updates = data.model_dump(exclude_unset=True)
    orden_changed = "orden" in updates and updates["orden"] != estado.orden
    for key, value in updates.items():
        setattr(estado, key, value)
    await db.flush()
    await db.refresh(estado)

    if orden_changed:
        await _recompute_all_estado_general(db)

    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cc_estado",
        resource_id=str(estado_id), payload=updates
    )
    return EstadoResponse.model_validate(estado)


async def eliminar_estado(db: AsyncSession, estado_id: int, actor: AuthUser) -> None:
    result = await db.execute(select(EstadoCordonCuneta).where(EstadoCordonCuneta.id == estado_id))
    estado = result.scalar_one_or_none()
    if not estado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Estado {estado_id} no encontrado"},
        )
    # Chequea todas las FK al catálogo: dimensiones, estado_general e historial
    mun_rows = (await db.execute(
        select(MunicipioCordonCuneta.municipio).where(
            MunicipioCordonCuneta.deleted_at.is_(None),
            (MunicipioCordonCuneta.ejuridico == estado_id)
            | (MunicipioCordonCuneta.etecnico == estado_id)
            | (MunicipioCordonCuneta.efinanciero == estado_id)
            | (MunicipioCordonCuneta.estado_general == estado_id),
        )
    )).scalars().all()
    ref_hist = (await db.execute(
        select(func.count(EstadoHistorialCC.id)).where(
            (EstadoHistorialCC.estado_anterior_id == estado_id)
            | (EstadoHistorialCC.estado_nuevo_id == estado_id)
        )
    )).scalar_one()
    if mun_rows or ref_hist > 0:
        parts = []
        if mun_rows:
            parts.append(f"municipios: {', '.join(mun_rows)}")
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
        db, actor=actor, action="DELETE", resource_type="cc_estado",
        resource_id=str(estado_id), payload={}
    )


async def actualizar_municipio(
    db: AsyncSession, municipio_id: str, data: MunicipioUpdate, actor: AuthUser
) -> MunicipioResponse:
    result = await db.execute(
        select(MunicipioCordonCuneta).where(
            MunicipioCordonCuneta.id == municipio_id,
            MunicipioCordonCuneta.deleted_at.is_(None),
        )
    )
    municipio = result.scalar_one_or_none()
    if not municipio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Municipio {municipio_id} no encontrado"},
        )

    updates = data.model_dump(exclude_unset=True)
    fecha_cambio = updates.pop("fecha_cambio", None)

    historial = []
    for campo in ("ejuridico", "etecnico", "efinanciero"):
        if campo in updates:
            old_val = getattr(municipio, campo)
            new_val = updates[campo]
            if new_val is not None and old_val != new_val:
                entry = EstadoHistorialCC(
                    municipio_id=municipio_id,
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
        setattr(municipio, key, value)

    if fecha_cambio is not None:
        municipio.updated_at = datetime.combine(fecha_cambio, dtime(12, 0, 0), tzinfo=timezone.utc)

    if "estado_general" not in updates:
        municipio.estado_general = await _compute_estado_general(
            db, [municipio.ejuridico, municipio.etecnico, municipio.efinanciero]
        )

    await db.flush()

    for entry in historial:
        db.add(entry)

    await db.flush()
    await db.refresh(municipio)
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordon_cuneta",
        resource_id=municipio_id, payload=updates
    )
    return MunicipioResponse.model_validate(municipio)


async def crear_municipio(
    db: AsyncSession, data: MunicipioCreate, actor: AuthUser
) -> MunicipioResponse:
    existing = (await db.execute(
        select(MunicipioCordonCuneta).where(
            func.lower(MunicipioCordonCuneta.municipio) == data.municipio.strip().lower(),
            func.lower(MunicipioCordonCuneta.departamento) == (data.departamento or '').strip().lower(),
            MunicipioCordonCuneta.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MUNICIPIO_DUPLICADO",
                "message": f"Ya existe '{existing.municipio}' ({existing.departamento}) en el panel.",
                "existing_id": existing.id,
            },
        )

    max_orden = (await db.execute(
        select(func.max(MunicipioCordonCuneta.orden)).where(MunicipioCordonCuneta.deleted_at.is_(None))
    )).scalar_one() or 0

    municipio = MunicipioCordonCuneta(
        orden=max_orden + 1,
        municipio=data.municipio,
        departamento=data.departamento,
        expediente=data.expediente,
        monto=data.monto,
        ok_gob=data.ok_gob,
        ejuridico=data.ejuridico,
        etecnico=data.etecnico,
        efinanciero=data.efinanciero,
        updated_by=actor.email,
    )
    db.add(municipio)
    try:
        await db.flush()
    except IntegrityError:
        # Doble-submit / creación concurrente: el pre-check de arriba no lo vio
        # a tiempo, pero la constraint única de DB sí lo bloqueó. Traducimos a
        # el mismo 409 legible en vez de dejar subir un 500 genérico.
        await db.rollback()
        existing = (await db.execute(
            select(MunicipioCordonCuneta).where(
                func.lower(MunicipioCordonCuneta.municipio) == data.municipio.strip().lower(),
                func.lower(MunicipioCordonCuneta.departamento) == (data.departamento or '').strip().lower(),
                MunicipioCordonCuneta.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MUNICIPIO_DUPLICADO",
                "message": (
                    f"Ya existe '{existing.municipio}' ({existing.departamento}) en el panel."
                    if existing else "Ya existe un municipio con ese nombre y departamento en el panel."
                ),
                "existing_id": existing.id if existing else None,
            },
        )

    municipio.estado_general = await _compute_estado_general(
        db, [municipio.ejuridico, municipio.etecnico, municipio.efinanciero]
    )
    await db.flush()
    await db.refresh(municipio)
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="cordon_cuneta",
        resource_id=municipio.id, payload=data.model_dump()
    )
    return MunicipioResponse.model_validate(municipio)


async def eliminar_municipio(db: AsyncSession, municipio_id: str, actor: AuthUser) -> None:
    result = await db.execute(
        select(MunicipioCordonCuneta).where(
            MunicipioCordonCuneta.id == municipio_id,
            MunicipioCordonCuneta.deleted_at.is_(None),
        )
    )
    municipio = result.scalar_one_or_none()
    if not municipio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Municipio {municipio_id} no encontrado"},
        )
    municipio.deleted_at = datetime.now(timezone.utc)
    municipio.updated_by = actor.email
    await db.flush()
    await log_audit(
        db, actor=actor, action="DELETE", resource_type="cordon_cuneta",
        resource_id=municipio_id, payload={}
    )


async def get_historial(
    db: AsyncSession, municipio_id: str
) -> list[EstadoHistorialResponse]:
    result = await db.execute(
        select(EstadoHistorialCC)
        .where(EstadoHistorialCC.municipio_id == municipio_id)
        .order_by(EstadoHistorialCC.created_at.desc())
    )
    return [EstadoHistorialResponse.model_validate(h) for h in result.scalars().all()]


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
    result = await db.execute(select(ConfigCordonCuneta).where(ConfigCordonCuneta.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = ConfigCordonCuneta(id=1, presupuesto=data.presupuesto)
        db.add(config)
    else:
        config.presupuesto = data.presupuesto
    await db.flush()
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="cordon_cuneta_config",
        resource_id="presupuesto", payload={"presupuesto": data.presupuesto}
    )
    return float(config.presupuesto)


async def listar_pedidos(db: AsyncSession, municipio_id: str, actor: AuthUser) -> list[PedidoResponse]:
    municipio = (await db.execute(
        select(MunicipioCordonCuneta).where(
            MunicipioCordonCuneta.id == municipio_id,
            MunicipioCordonCuneta.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not municipio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Municipio {municipio_id} no encontrado"},
        )
    query = (
        select(PedidoCordonCuneta)
        .where(PedidoCordonCuneta.municipio_id == municipio_id)
    )
    # supervision y Admin ven todo
    # infraestructura ve vivienda + infraestructura (no supervision)
    # resto ve solo vivienda (no infraestructura, no supervision)
    actor_secs = set(actor.secretarias)
    if actor.role != "Admin" and "supervision" not in actor_secs:
        if "infraestructura" in actor_secs:
            query = query.where(
                (PedidoCordonCuneta.secretaria != "supervision")
                | PedidoCordonCuneta.secretaria.is_(None)
            )
        else:
            query = query.where(
                PedidoCordonCuneta.secretaria.not_in(["infraestructura", "supervision"])
                | PedidoCordonCuneta.secretaria.is_(None)
            )
    query = query.order_by(PedidoCordonCuneta.fecha_pedido.desc())
    result = await db.execute(query)
    return [PedidoResponse.model_validate(p) for p in result.scalars().all()]


async def crear_pedido(
    db: AsyncSession, municipio_id: str, data: PedidoCreate, actor: AuthUser
) -> PedidoResponse:
    municipio = (await db.execute(
        select(MunicipioCordonCuneta).where(
            MunicipioCordonCuneta.id == municipio_id,
            MunicipioCordonCuneta.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not municipio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RECURSO_NO_ENCONTRADO", "message": f"Municipio {municipio_id} no encontrado"},
        )
    actor_secs = set(actor.secretarias)
    secretaria = None
    if "supervision" in actor_secs:
        secretaria = "supervision"
    elif "infraestructura" in actor_secs:
        secretaria = "infraestructura"
    elif actor.secretarias:
        secretaria = actor.secretarias[0]

    pedido = PedidoCordonCuneta(
        municipio_id=municipio_id,
        descripcion=data.descripcion,
        fecha_pedido=data.fecha_pedido,
        created_by=actor.email,
        created_by_nombre=actor.nombre,
        secretaria=secretaria,
    )
    db.add(pedido)
    await db.flush()
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="cc_pedido",
        resource_id=pedido.id, payload={"municipio_id": municipio_id, "fecha_pedido": str(data.fecha_pedido)}
    )
    return PedidoResponse.model_validate(pedido)


async def delete_pedido(
    db: AsyncSession, municipio_id: str, pedido_id: str, actor: AuthUser
) -> None:
    result = await db.execute(
        select(PedidoCordonCuneta).where(
            PedidoCordonCuneta.id == pedido_id,
            PedidoCordonCuneta.municipio_id == municipio_id,
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
        db, actor=actor, action="DELETE", resource_type="cc_pedido",
        resource_id=pedido_id, payload={"municipio_id": municipio_id}
    )


async def seed_cordon_cuneta(db: AsyncSession) -> None:
    count = (await db.execute(select(func.count(MunicipioCordonCuneta.id)))).scalar_one()
    if count > 0:
        return

    for e in ESTADOS_SEED:
        db.add(EstadoCordonCuneta(**e))
    await db.flush()

    for m in MUNICIPIOS_SEED:
        db.add(MunicipioCordonCuneta(**m))
    await db.flush()

    config = ConfigCordonCuneta(id=1, presupuesto=0)
    db.add(config)
    await db.flush()
