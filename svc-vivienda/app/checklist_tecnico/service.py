import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import AuthUser
from app.checklist_tecnico import catalog
from app.checklist_tecnico.models import (
    CatalogoEstadoExpediente,
    CatalogoReparticion,
    ChecklistItem,
    ChecklistObraHito,
    ChecklistTecnico,
)
from app.checklist_tecnico.schemas import (
    CatalogoEstadoExpedienteCreate,
    CatalogoEstadoExpedienteResponse,
    CatalogoEstadoExpedienteUpdate,
    CatalogoReparticionCreate,
    CatalogoReparticionResponse,
    CatalogoReparticionUpdate,
    CatalogosResponse,
    ChecklistItemResponse,
    ChecklistItemUpdate,
    ChecklistPedidoCreate,
    ChecklistPedidoOut,
    ChecklistTecnicoResponse,
    ChecklistTecnicoUpdate,
    EntidadListItem,
    EntidadResumen,
    HitoResponse,
    HitoUpdate,
    ItemDefinicion,
)
from app.cordoba_hogar import service as ch_service
from app.cordoba_hogar.models import LocalidadCordobaHogar
from app.cordon_cuneta import service as cc_service
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.mi_lugar import service as ml_service
from app.mi_lugar.models import ProyectoML


def _recurso_no_encontrado(mensaje: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "RECURSO_NO_ENCONTRADO", "message": mensaje},
    )


def _validar_programa(programa: str) -> None:
    if programa not in catalog.PROGRAMAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROGRAMA_INVALIDO", "message": f"Programa desconocido: {programa}"},
        )


async def _get_entidad(db: AsyncSession, programa: str, entidad_id: str):
    """Busca la fila en viv_cordon_cuneta / viv_cordoba_hogar / viv_ml_proyectos según programa."""
    if programa == "cc":
        result = await db.execute(
            select(MunicipioCordonCuneta).where(
                MunicipioCordonCuneta.id == entidad_id, MunicipioCordonCuneta.deleted_at.is_(None)
            )
        )
    elif programa == "ch":
        result = await db.execute(
            select(LocalidadCordobaHogar).where(
                LocalidadCordobaHogar.id == entidad_id, LocalidadCordobaHogar.deleted_at.is_(None)
            )
        )
    else:  # ml
        result = await db.execute(
            select(ProyectoML).where(ProyectoML.id == entidad_id, ProyectoML.deleted_at.is_(None))
        )
    entidad = result.scalar_one_or_none()
    if entidad is None:
        raise _recurso_no_encontrado(f"No existe una entidad de {programa} con id {entidad_id}")
    return entidad


def _entidad_resumen(programa: str, entidad) -> EntidadResumen:
    if programa == "cc":
        dato_extra = None
        if entidad.cordon_cuneta_ml or entidad.adoquinado_m2:
            partes = []
            if entidad.cordon_cuneta_ml:
                partes.append(f"{entidad.cordon_cuneta_ml} ml")
            if entidad.adoquinado_m2:
                partes.append(f"{entidad.adoquinado_m2} m²")
            dato_extra = " · ".join(partes)
        return EntidadResumen(
            nombre=entidad.municipio,
            departamento=entidad.departamento,
            expediente=entidad.expediente,
            monto=float(entidad.monto) if entidad.monto is not None else None,
            dato_extra_label="Cordón cuneta / adoquinado" if dato_extra else None,
            dato_extra_valor=dato_extra,
        )
    if programa == "ch":
        return EntidadResumen(
            nombre=entidad.localidad,
            departamento=entidad.departamento,
            expediente=entidad.expediente,
            monto=float(entidad.monto) if entidad.monto is not None else None,
            dato_extra_label="Cantidad de viviendas" if entidad.cantidad_casas else None,
            dato_extra_valor=str(entidad.cantidad_casas) if entidad.cantidad_casas else None,
        )
    # ml
    return EntidadResumen(
        nombre=entidad.nombre or entidad.localidad_nombre,
        departamento=entidad.departamento,
        expediente=entidad.expediente,
        monto=float(entidad.monto) if entidad.monto is not None else None,
        dato_extra_label="Cantidad de lotes" if entidad.lotes else None,
        dato_extra_valor=str(entidad.lotes) if entidad.lotes else None,
    )


async def _get_or_create_checklist(
    db: AsyncSession, programa: str, entidad_id: str, actor: AuthUser | None = None
) -> ChecklistTecnico:
    result = await db.execute(
        select(ChecklistTecnico).where(
            ChecklistTecnico.programa == programa, ChecklistTecnico.entidad_id == entidad_id
        )
    )
    checklist = result.scalar_one_or_none()
    if checklist is not None:
        return checklist

    checklist = ChecklistTecnico(
        id=str(uuid.uuid4()),
        programa=programa,
        entidad_id=entidad_id,
        updated_by=actor.email if actor else None,
    )
    db.add(checklist)
    await db.flush()

    for item_num, sub_item_num in catalog.todos_los_item_keys(programa):
        db.add(
            ChecklistItem(
                id=str(uuid.uuid4()),
                checklist_id=checklist.id,
                item_num=item_num,
                sub_item_num=sub_item_num,
                valor="sin_presentar",
            )
        )

    if programa == "cc":
        for tipo in catalog.HITOS_TIPOS:
            db.add(ChecklistObraHito(id=str(uuid.uuid4()), checklist_id=checklist.id, tipo=tipo))

    await db.flush()
    if actor:
        await log_audit(
            db, actor=actor, action="CREATE", resource_type="checklist_tecnico",
            resource_id=checklist.id, payload={"programa": programa, "entidad_id": entidad_id},
        )
    return checklist


async def _catalogo_labels(db: AsyncSession) -> tuple[dict[int, str], dict[int, str]]:
    estados = (await db.execute(select(CatalogoEstadoExpediente))).scalars().all()
    reparticiones = (await db.execute(select(CatalogoReparticion))).scalars().all()
    return (
        {e.id: e.label for e in estados},
        {r.id: r.label for r in reparticiones},
    )


async def _build_response(db: AsyncSession, programa: str, checklist: ChecklistTecnico, entidad) -> ChecklistTecnicoResponse:
    estado_labels, reparticion_labels = await _catalogo_labels(db)

    items_result = await db.execute(
        select(ChecklistItem)
        .where(ChecklistItem.checklist_id == checklist.id)
        .order_by(ChecklistItem.item_num, ChecklistItem.sub_item_num)
    )
    items = [
        ChecklistItemResponse(
            item_num=i.item_num,
            sub_item_num=i.sub_item_num,
            label=catalog.item_label(programa, i.item_num, i.sub_item_num) or "",
            valor=i.valor,
        )
        for i in items_result.scalars().all()
    ]

    hitos: list[HitoResponse] | None = None
    if programa == "cc":
        hitos_result = await db.execute(
            select(ChecklistObraHito).where(ChecklistObraHito.checklist_id == checklist.id)
        )
        monto_convenio = float(entidad.monto) if entidad.monto is not None else None
        hitos = []
        for h in hitos_result.scalars().all():
            if h.tipo == "100":
                monto = 0.0
            else:
                monto = round(monto_convenio * catalog.HITOS_PORCENTAJE[h.tipo], 2) if monto_convenio else None
            hitos.append(
                HitoResponse(
                    tipo=h.tipo, label=catalog.HITOS_LABEL[h.tipo], monto=monto, fecha_acreditado=h.fecha_acreditado
                )
            )
        hitos.sort(key=lambda h: catalog.HITOS_TIPOS.index(h.tipo))

    return ChecklistTecnicoResponse(
        programa=programa,
        entidad_id=checklist.entidad_id,
        entidad=_entidad_resumen(programa, entidad),
        estado_expediente_id=checklist.estado_expediente_id,
        estado_expediente_label=estado_labels.get(checklist.estado_expediente_id) if checklist.estado_expediente_id else None,
        fecha_radicacion=checklist.fecha_radicacion,
        reparticion_id=checklist.reparticion_id,
        reparticion_label=reparticion_labels.get(checklist.reparticion_id) if checklist.reparticion_id else None,
        items=items,
        hitos=hitos,
        updated_at=checklist.updated_at,
        updated_by=checklist.updated_by,
    )


async def get_checklist(db: AsyncSession, programa: str, entidad_id: str) -> ChecklistTecnicoResponse:
    _validar_programa(programa)
    entidad = await _get_entidad(db, programa, entidad_id)
    checklist = await _get_or_create_checklist(db, programa, entidad_id)
    return await _build_response(db, programa, checklist, entidad)


async def listar_entidades(db: AsyncSession) -> list[EntidadListItem]:
    """Filas mínimas (programa, id, nombre, departamento) para el selector del panel.

    Existe porque TecnicoDGV no puede llamar a los GET de panel completo de
    cordon_cuneta/cordoba_hogar/mi_lugar (spec §8). Devuelve las 3 fuentes juntas;
    el frontend agrupa por localidad. Solo entidades no borradas.
    """
    out: list[EntidadListItem] = []

    cc = await db.execute(
        select(MunicipioCordonCuneta)
        .where(MunicipioCordonCuneta.deleted_at.is_(None))
        .order_by(MunicipioCordonCuneta.municipio)
    )
    for m in cc.scalars().all():
        out.append(EntidadListItem(programa="cc", id=m.id, nombre=m.municipio, departamento=m.departamento))

    ch = await db.execute(
        select(LocalidadCordobaHogar)
        .where(LocalidadCordobaHogar.deleted_at.is_(None))
        .order_by(LocalidadCordobaHogar.localidad)
    )
    for loc in ch.scalars().all():
        out.append(EntidadListItem(programa="ch", id=loc.id, nombre=loc.localidad, departamento=loc.departamento))

    ml = await db.execute(
        select(ProyectoML)
        .where(ProyectoML.deleted_at.is_(None))
        .order_by(ProyectoML.nombre)
    )
    for p in ml.scalars().all():
        out.append(
            EntidadListItem(
                programa="ml",
                id=p.id,
                nombre=p.nombre or p.localidad_nombre,
                departamento=p.departamento,
            )
        )

    return out


# ── Observaciones (pedidos) — delega en el service del programa correspondiente ──
# El panel comparte la sección "Observaciones" con los 3 paneles completos, pero
# TecnicoDGV no puede pegarle a /{programa}/{id}/pedidos directo (ROLES_LECTURA).
# Estos wrappers reusan la lógica existente (incluye validación de entidad 404 y
# enmascarado de comunicaciones de infra/supervisión) pasando el actor tal cual.

async def listar_pedidos(
    db: AsyncSession, programa: str, entidad_id: str, actor: AuthUser
) -> list[ChecklistPedidoOut]:
    _validar_programa(programa)
    if programa == "cc":
        pedidos = await cc_service.listar_pedidos(db, entidad_id, actor)
    elif programa == "ch":
        pedidos = await ch_service.listar_pedidos(db, entidad_id, actor)
    else:
        pedidos = await ml_service.listar_pedidos_ml(db, entidad_id, actor)
    return [ChecklistPedidoOut.model_validate(p) for p in pedidos]


async def crear_pedido(
    db: AsyncSession, programa: str, entidad_id: str, data: ChecklistPedidoCreate, actor: AuthUser
) -> ChecklistPedidoOut:
    _validar_programa(programa)
    if programa == "cc":
        from app.cordon_cuneta.schemas import PedidoCreate as _PedidoCreate

        pedido = await cc_service.crear_pedido(db, entidad_id, _PedidoCreate(**data.model_dump()), actor)
    elif programa == "ch":
        from app.cordoba_hogar.schemas import PedidoCreate as _PedidoCreate

        pedido = await ch_service.crear_pedido(db, entidad_id, _PedidoCreate(**data.model_dump()), actor)
    else:
        from app.mi_lugar.schemas import PedidoMLCreate as _PedidoMLCreate

        pedido = await ml_service.crear_pedido_ml(db, entidad_id, _PedidoMLCreate(**data.model_dump()), actor)
    return ChecklistPedidoOut.model_validate(pedido)


async def actualizar_checklist(
    db: AsyncSession, programa: str, entidad_id: str, data: ChecklistTecnicoUpdate, actor: AuthUser
) -> ChecklistTecnicoResponse:
    _validar_programa(programa)
    entidad = await _get_entidad(db, programa, entidad_id)
    checklist = await _get_or_create_checklist(db, programa, entidad_id, actor)

    updates = data.model_dump(exclude_unset=True)
    if "estado_expediente_id" in updates and updates["estado_expediente_id"] is not None:
        exists = await db.get(CatalogoEstadoExpediente, updates["estado_expediente_id"])
        if not exists:
            raise _recurso_no_encontrado("Estado del expediente no encontrado en el catálogo")
    if "reparticion_id" in updates and updates["reparticion_id"] is not None:
        exists = await db.get(CatalogoReparticion, updates["reparticion_id"])
        if not exists:
            raise _recurso_no_encontrado("Repartición no encontrada en el catálogo")

    for key, value in updates.items():
        setattr(checklist, key, value)
    checklist.updated_by = actor.email
    await db.flush()
    await db.refresh(checklist)

    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="checklist_tecnico",
        resource_id=checklist.id, payload=updates,
    )
    return await _build_response(db, programa, checklist, entidad)


async def actualizar_item(
    db: AsyncSession, programa: str, entidad_id: str, item_num: int, data: ChecklistItemUpdate, actor: AuthUser
) -> ChecklistTecnicoResponse:
    _validar_programa(programa)
    if catalog.item_label(programa, item_num, data.sub_item_num) is None:
        raise _recurso_no_encontrado(
            f"El ítem {item_num}" + (f" (sub-ítem {data.sub_item_num})" if data.sub_item_num else "")
            + f" no existe para el programa {programa}"
        )
    entidad = await _get_entidad(db, programa, entidad_id)
    checklist = await _get_or_create_checklist(db, programa, entidad_id, actor)

    result = await db.execute(
        select(ChecklistItem).where(
            ChecklistItem.checklist_id == checklist.id,
            ChecklistItem.item_num == item_num,
            ChecklistItem.sub_item_num == data.sub_item_num,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        # Defensivo — no debería pasar, _get_or_create_checklist ya inicializa todos los ítems.
        item = ChecklistItem(
            id=str(uuid.uuid4()), checklist_id=checklist.id, item_num=item_num, sub_item_num=data.sub_item_num
        )
        db.add(item)
    item.valor = data.valor
    checklist.updated_by = actor.email
    checklist.updated_at = datetime.now(timezone.utc)
    await db.flush()

    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="checklist_tecnico_item",
        resource_id=f"{checklist.id}:{item_num}:{data.sub_item_num or ''}",
        payload={"valor": data.valor},
    )
    return await _build_response(db, programa, checklist, entidad)


async def actualizar_hito(
    db: AsyncSession, programa: str, entidad_id: str, tipo: str, data: HitoUpdate, actor: AuthUser
) -> ChecklistTecnicoResponse:
    _validar_programa(programa)
    if programa != "cc":
        raise _recurso_no_encontrado("Los hitos de obra solo están disponibles para Cordón Cuneta en esta entrega")
    if tipo not in catalog.HITOS_TIPOS:
        raise _recurso_no_encontrado(f"Tipo de hito desconocido: {tipo}")

    entidad = await _get_entidad(db, programa, entidad_id)
    checklist = await _get_or_create_checklist(db, programa, entidad_id, actor)

    result = await db.execute(
        select(ChecklistObraHito).where(
            ChecklistObraHito.checklist_id == checklist.id, ChecklistObraHito.tipo == tipo
        )
    )
    hito = result.scalar_one_or_none()
    if hito is None:
        hito = ChecklistObraHito(id=str(uuid.uuid4()), checklist_id=checklist.id, tipo=tipo)
        db.add(hito)
    hito.fecha_acreditado = data.fecha_acreditado
    checklist.updated_by = actor.email
    checklist.updated_at = datetime.now(timezone.utc)
    await db.flush()

    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="checklist_tecnico_hito",
        resource_id=f"{checklist.id}:{tipo}", payload={"fecha_acreditado": str(data.fecha_acreditado)},
    )
    return await _build_response(db, programa, checklist, entidad)


# ── Catálogos administrables ──────────────────────────────────────────────

async def get_catalogos(db: AsyncSession) -> CatalogosResponse:
    estados = (
        await db.execute(select(CatalogoEstadoExpediente).order_by(CatalogoEstadoExpediente.orden))
    ).scalars().all()
    reparticiones = (
        await db.execute(select(CatalogoReparticion).order_by(CatalogoReparticion.orden))
    ).scalars().all()
    return CatalogosResponse(
        estados_expediente=[CatalogoEstadoExpedienteResponse.model_validate(e) for e in estados],
        reparticiones=[CatalogoReparticionResponse.model_validate(r) for r in reparticiones],
        items_por_programa={
            programa: [ItemDefinicion(**d) for d in catalog.items_definition(programa)]
            for programa in catalog.PROGRAMAS
        },
    )


async def crear_estado_expediente(
    db: AsyncSession, data: CatalogoEstadoExpedienteCreate, actor: AuthUser
) -> CatalogoEstadoExpedienteResponse:
    new_id = int(time.time() * 1000)
    estado = CatalogoEstadoExpediente(id=new_id, label=data.label, orden=data.orden, activo=data.activo)
    db.add(estado)
    await db.flush()
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="checklist_estado_expediente",
        resource_id=str(new_id), payload=data.model_dump(),
    )
    return CatalogoEstadoExpedienteResponse.model_validate(estado)


async def actualizar_estado_expediente(
    db: AsyncSession, estado_id: int, data: CatalogoEstadoExpedienteUpdate, actor: AuthUser
) -> CatalogoEstadoExpedienteResponse:
    estado = await db.get(CatalogoEstadoExpediente, estado_id)
    if not estado:
        raise _recurso_no_encontrado(f"Estado del expediente {estado_id} no encontrado")
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(estado, key, value)
    await db.flush()
    await db.refresh(estado)
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="checklist_estado_expediente",
        resource_id=str(estado_id), payload=updates,
    )
    return CatalogoEstadoExpedienteResponse.model_validate(estado)


async def crear_reparticion(
    db: AsyncSession, data: CatalogoReparticionCreate, actor: AuthUser
) -> CatalogoReparticionResponse:
    new_id = int(time.time() * 1000)
    reparticion = CatalogoReparticion(
        id=new_id, programa=data.programa, label=data.label, orden=data.orden, activo=data.activo
    )
    db.add(reparticion)
    await db.flush()
    await log_audit(
        db, actor=actor, action="CREATE", resource_type="checklist_reparticion",
        resource_id=str(new_id), payload=data.model_dump(),
    )
    return CatalogoReparticionResponse.model_validate(reparticion)


async def actualizar_reparticion(
    db: AsyncSession, reparticion_id: int, data: CatalogoReparticionUpdate, actor: AuthUser
) -> CatalogoReparticionResponse:
    reparticion = await db.get(CatalogoReparticion, reparticion_id)
    if not reparticion:
        raise _recurso_no_encontrado(f"Repartición {reparticion_id} no encontrada")
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(reparticion, key, value)
    await db.flush()
    await db.refresh(reparticion)
    await log_audit(
        db, actor=actor, action="UPDATE", resource_type="checklist_reparticion",
        resource_id=str(reparticion_id), payload=updates,
    )
    return CatalogoReparticionResponse.model_validate(reparticion)
