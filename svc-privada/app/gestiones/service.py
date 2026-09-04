"""Lógica de gestiones — port del sistema viejo (BigQuery) a PostgreSQL.

Panel-module (ADR-009): queries inline, sin repository.py. Respuestas
byte-compatibles con el sistema viejo (Anexo D), salvo:
- lock optimista sobre `updated_at` en vez de `fecha_ingreso` (§3.6),
- `estado = FINALIZADA` setea `fecha_finalizacion` (RE-9),
- UTF-8 correcto (el viejo devuelve mojibake en textos).
"""
import json
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AuthUser
from app.common import as_float, dias_transcurridos, iso, norm, now_utc
from app.gestiones.models import ESTADOS, Gestion, GestionEvento
from app.gestiones.schemas import CambioEstado, DetalleCorreccion, GestionCreate, GestionUpdate, LocalidadInfoUpsert
from app.territorial.models import DepartamentoInfo, GeoLocalidad, LocalidadInfo

_CERRADOS = {"FINALIZADA", "ARCHIVADO"}

# Eventos que quedan en `priv_gestiones_eventos` (auditoría interna) pero no se muestran
# en el timeline de Movimientos del usuario — ver DetalleCorreccion.
_TIPO_EVENTO_OCULTO = {"CORRECCION_DETALLE"}


def _err(code: int, detail):
    raise HTTPException(status_code=code, detail=detail)


def _meta_dumps(meta: dict) -> str:
    return json.dumps(meta, ensure_ascii=False, default=str)


# ── serializadores de fila ──────────────────────────────────────────────────

def _list_item(g: Gestion) -> dict:
    return {
        "id_gestion": g.id,
        "departamento": g.departamento,
        "localidad": g.localidad,
        "estado": g.estado,
        "urgencia": g.urgencia,
        "ministerio_agencia_id": g.ministerio_agencia_id,
        "categoria_general_id": g.categoria_general_id,
        "tipo_gestion": g.tipo_gestion,
        "canal_origen": g.canal_origen,
        "detalle": g.detalle,
        "costo_estimado": as_float(g.costo_estimado),
        "costo_moneda": g.costo_moneda,
        "nro_expediente": g.nro_expediente,
        "fecha_ingreso": iso(g.fecha_ingreso),
        "dias_transcurridos": dias_transcurridos(g.fecha_estado),
        "categoria_id": g.categoria_id,
        "programa_id": g.programa_id,
        "area_id": g.area_id,
        "ok_gobernador": g.ok_gobernador,
        "ok_ministro": g.ok_ministro,
        "updated_at": iso(g.updated_at),
    }


def _detail(g: Gestion) -> dict:
    return {
        "id_gestion": g.id,
        "nro_expediente": g.nro_expediente,
        "origen": g.origen,
        "estado": g.estado,
        "fecha_ingreso": iso(g.fecha_ingreso),
        "fecha_estado": iso(g.fecha_estado),
        "fecha_finalizacion": iso(g.fecha_finalizacion),
        "urgencia": g.urgencia,
        "ministerio_agencia_id": g.ministerio_agencia_id,
        "organismo_id": g.organismo_id,
        "derivado_a_id": g.derivado_a_id,
        "categoria_general_id": g.categoria_general_id,
        "subcategoria_id": g.subcategoria_id,
        "tipo_demanda_principal_id": g.tipo_demanda_principal_id,
        "subtipo_detalle": g.subtipo_detalle,
        "detalle": g.detalle,
        "observaciones": g.observaciones,
        "geo_id": g.geo_id,
        "departamento": g.departamento,
        "localidad": g.localidad,
        "direccion": g.direccion,
        "lat": as_float(g.lat),
        "lon": as_float(g.lon),
        "costo_estimado": as_float(g.costo_estimado),
        "costo_moneda": g.costo_moneda,
        "created_at": iso(g.created_at),
        "created_by": g.created_by,
        "updated_at": iso(g.updated_at),
        "updated_by": g.updated_by,
        "is_deleted": g.deleted_at is not None,
        "tipo_gestion": g.tipo_gestion,
        "canal_origen": g.canal_origen,
        "categoria_id": g.categoria_id,
        "programa_id": g.programa_id,
        "area_id": g.area_id,
        "ok_gobernador": g.ok_gobernador,
        "ok_ministro": g.ok_ministro,
        "acciones_implementadas": g.acciones_implementadas,
    }


def _resumen_gestion(g: Gestion) -> dict:
    return {
        "id_gestion": g.id,
        "estado": g.estado,
        "urgencia": g.urgencia,
        "ministerio_agencia_id": g.ministerio_agencia_id,
        "categoria_general_id": g.categoria_general_id,
        "tipo_gestion": g.tipo_gestion,
        "canal_origen": g.canal_origen,
        "detalle": g.detalle,
        "subtipo_detalle": g.subtipo_detalle,
        "observaciones": g.observaciones,
        "nro_expediente": g.nro_expediente,
        "fecha_ingreso": iso(g.fecha_ingreso),
        "fecha_estado": iso(g.fecha_estado),
        "costo_estimado": as_float(g.costo_estimado),
        "costo_moneda": g.costo_moneda,
        "direccion": g.direccion,
        "departamento": g.departamento,
        "localidad": g.localidad,
    }


def _evento(e: GestionEvento, *, meta_as_str: bool) -> dict:
    meta = e.metadata_json
    if meta_as_str and meta is not None and not isinstance(meta, str):
        meta = _meta_dumps(meta)
    return {
        "id_evento": e.id,
        "id_gestion": e.gestion_id,
        "fecha_evento": iso(e.fecha_evento),
        "usuario": e.usuario,
        "rol_usuario": e.rol_usuario,
        "tipo_evento": e.tipo_evento,
        "estado_anterior": e.estado_anterior,
        "estado_nuevo": e.estado_nuevo,
        "campo_modificado": e.campo_modificado,
        "valor_anterior": e.valor_anterior,
        "valor_nuevo": e.valor_nuevo,
        "comentario": e.comentario,
        "metadata_json": meta,
    }


# ── lookups ────────────────────────────────────────────────────────────────

async def _geo_lookup(db: AsyncSession, departamento: str, localidad: str) -> dict | None:
    row = (
        await db.execute(
            select(GeoLocalidad).where(
                GeoLocalidad.activo.is_(True),
                func.upper(func.trim(GeoLocalidad.departamento)) == norm(departamento),
                func.upper(func.trim(GeoLocalidad.localidad)) == norm(localidad),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "id_geo": row.id_geo,
        "departamento": row.departamento,
        "localidad": row.localidad,
        "lat": as_float(row.lat),
        "lon": as_float(row.lon),
    }


async def _resolve(db: AsyncSession, id_or_legacy: str, *, incluir_borradas: bool = False) -> Gestion | None:
    cond = or_(Gestion.id == id_or_legacy, Gestion.id_legacy == id_or_legacy)
    if not incluir_borradas:
        cond = and_(cond, Gestion.deleted_at.is_(None))
    return (await db.execute(select(Gestion).where(cond).limit(1))).scalar_one_or_none()


# ── endpoints ──────────────────────────────────────────────────────────────

# Columnas por las que se puede ordenar la lista (whitelist — el valor es la
# columna del modelo). `dias_transcurridos` es derivado de `fecha_estado` (a más
# días, fecha más vieja) → se ordena por esa columna con el sentido invertido.
_SORT_COLS = {
    "fecha_ingreso": Gestion.fecha_ingreso,
    "fecha_estado": Gestion.fecha_estado,
    "dias_transcurridos": Gestion.fecha_estado,
    "estado": Gestion.estado,
    "urgencia": Gestion.urgencia,
    "departamento": Gestion.departamento,
    "localidad": Gestion.localidad,
    "nro_expediente": Gestion.nro_expediente,
    "costo_estimado": Gestion.costo_estimado,
    "ministerio": Gestion.ministerio_agencia_id,
    "categoria": Gestion.categoria_general_id,
    "tipo_gestion": Gestion.tipo_gestion,
    "canal_origen": Gestion.canal_origen,
}


async def listar_gestiones(
    db: AsyncSession,
    *,
    estado=None, ministerio=None, categoria=None, departamento=None, localidad=None,
    q=None, tipo_gestion=None, canal_origen=None, ok_gobernador=None, ok_ministro=None,
    categoria_id=None, programa_id=None, area_id=None,
    sort=None, sort_dir="desc", limit=50, offset=0,
) -> dict:
    conds = [Gestion.deleted_at.is_(None)]
    if estado:
        conds.append(Gestion.estado == estado)
    if ministerio:
        conds.append(Gestion.ministerio_agencia_id == ministerio)
    if categoria:
        conds.append(Gestion.categoria_general_id == categoria)
    if categoria_id is not None:
        conds.append(Gestion.categoria_id == categoria_id)
    if programa_id is not None:
        conds.append(Gestion.programa_id == programa_id)
    if area_id is not None:
        conds.append(Gestion.area_id == area_id)
    if ok_gobernador:
        conds.append(Gestion.ok_gobernador == ok_gobernador)
    if ok_ministro:
        conds.append(Gestion.ok_ministro == ok_ministro)
    if departamento:
        conds.append(func.upper(func.trim(Gestion.departamento)) == norm(departamento))
    if localidad:
        conds.append(func.upper(func.trim(Gestion.localidad)) == norm(localidad))
    if tipo_gestion:
        conds.append(Gestion.tipo_gestion == tipo_gestion)
    if canal_origen:
        conds.append(Gestion.canal_origen == canal_origen)
    if q:
        like = f"%{q.lower()}%"
        campos = [
            Gestion.id, Gestion.departamento, Gestion.localidad, Gestion.estado,
            Gestion.urgencia, Gestion.detalle, Gestion.subtipo_detalle,
            Gestion.nro_expediente, Gestion.costo_estimado,
            Gestion.costo_moneda, Gestion.tipo_gestion, Gestion.canal_origen,
        ]
        conds.append(or_(*[func.lower(func.cast(c, String)).like(like) for c in campos]))

    where = and_(*conds)
    total = (await db.execute(select(func.count()).select_from(Gestion).where(where))).scalar_one()

    col = _SORT_COLS.get(sort) if sort else None
    if col is not None:
        asc = str(sort_dir).lower() != "desc"
        # `dias_transcurridos` va al revés: más días == fecha más vieja
        if sort == "dias_transcurridos":
            asc = not asc
        primary = col.asc() if asc else col.desc()
        order_by = (primary, Gestion.id)
    else:
        order_by = (Gestion.fecha_ingreso.desc(), Gestion.fecha_estado.desc(), Gestion.id)

    rows = (
        await db.execute(
            select(Gestion).where(where).order_by(*order_by).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {"items": [_list_item(g) for g in rows], "total": int(total), "limit": limit, "offset": offset}


async def get_gestion(db: AsyncSession, id_or_legacy: str) -> dict:
    g = await _resolve(db, id_or_legacy)
    if g is None:
        _err(404, "Gestión no encontrada")
    return _detail(g)


async def listar_eventos(db: AsyncSession, id_or_legacy: str) -> list[dict]:
    g = await _resolve(db, id_or_legacy, incluir_borradas=True)
    gid = g.id if g else id_or_legacy
    rows = (
        await db.execute(
            select(GestionEvento).where(
                GestionEvento.gestion_id == gid,
                GestionEvento.tipo_evento.notin_(_TIPO_EVENTO_OCULTO),
            )
            .order_by(GestionEvento.fecha_evento.desc())
        )
    ).scalars().all()
    return [_evento(e, meta_as_str=False) for e in rows]


def _nuevo_evento(gid: str, actor: AuthUser, tipo: str, **kw) -> GestionEvento:
    return GestionEvento(
        id=str(uuid.uuid4()),
        gestion_id=gid,
        fecha_evento=now_utc(),
        usuario=actor.email or actor.uid or "",
        rol_usuario=actor.role,
        tipo_evento=tipo,
        estado_anterior=kw.get("estado_anterior"),
        estado_nuevo=kw.get("estado_nuevo"),
        campo_modificado=kw.get("campo_modificado"),
        valor_anterior=kw.get("valor_anterior"),
        valor_nuevo=kw.get("valor_nuevo"),
        comentario=kw.get("comentario"),
        metadata_json=kw.get("metadata_json"),
    )


async def crear_gestion(db: AsyncSession, actor: AuthUser, payload: GestionCreate) -> dict:
    geo = await _geo_lookup(db, payload.departamento, payload.localidad)
    if geo is None:
        _err(400, "Departamento/Localidad inválidos (no existen en geo_localidades)")

    now = now_utc()
    new_id = str(uuid.uuid4())
    g = Gestion(
        id=new_id,
        origen="APP",
        estado="INGRESADO",
        fecha_ingreso=date.today(),
        fecha_estado=now,
        urgencia=payload.urgencia or "Media",
        ministerio_agencia_id=payload.ministerio_agencia_id,
        organismo_id=payload.organismo_id,
        categoria_general_id=payload.categoria_general_id,
        subtipo_detalle=payload.subtipo_detalle,
        detalle=payload.detalle,
        observaciones=payload.observaciones,
        geo_id=geo["id_geo"],
        departamento=payload.departamento,
        localidad=payload.localidad,
        direccion=payload.direccion,
        lat=geo["lat"],
        lon=geo["lon"],
        costo_estimado=payload.costo_estimado,
        costo_moneda=payload.costo_moneda,
        nro_expediente=payload.nro_expediente,
        tipo_gestion=payload.tipo_gestion,
        canal_origen=payload.canal_origen,
        categoria_id=payload.categoria_id,
        programa_id=payload.programa_id,
        area_id=payload.area_id,
        ok_gobernador=payload.ok_gobernador or "PENDIENTE",
        ok_ministro=payload.ok_ministro or "PENDIENTE",
        acciones_implementadas=payload.acciones_implementadas,
        created_at=now,
        updated_at=now,
        created_by=actor.email or actor.uid,
        updated_by=actor.email or actor.uid,
    )
    db.add(g)

    meta = {
        "ministerio_agencia_id": payload.ministerio_agencia_id,
        "categoria_general_id": payload.categoria_general_id,
        "organismo_id": payload.organismo_id,
        "subtipo_detalle": payload.subtipo_detalle,
        "costo_estimado": payload.costo_estimado,
        "costo_moneda": payload.costo_moneda,
        "nro_expediente": payload.nro_expediente,
        "departamento": payload.departamento,
        "localidad": payload.localidad,
        "geo_id": geo["id_geo"],
        "tipo_gestion": payload.tipo_gestion,
        "canal_origen": payload.canal_origen,
    }
    db.add(_nuevo_evento(new_id, actor, "CREACION", estado_nuevo="INGRESADO", metadata_json=meta))
    await db.flush()
    await audit.log_audit(db, actor=actor, action="CREATE", resource_type="privada_gestion", resource_id=new_id, payload={"detalle": payload.detalle})
    return {"id_gestion": new_id}


def _check_lock(g: Gestion, updated_at: datetime | None):
    if updated_at is None:
        return
    a = g.updated_at
    b = updated_at
    if a is not None and a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b is not None and b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    if a != b:
        _err(status.HTTP_409_CONFLICT, {
            "code": "CONFLICTO_ESTADO",
            "message": "La gestión fue modificada por otro usuario. Recargá y reintentá.",
        })


async def cambiar_estado(db: AsyncSession, actor: AuthUser, id_or_legacy: str, payload: CambioEstado) -> dict:
    if payload.nuevo_estado not in ESTADOS:
        _err(422, {"code": "VALIDACION_FALLIDA", "message": f"estado inválido: {payload.nuevo_estado}"})
    g = await _resolve(db, id_or_legacy)
    if g is None:
        _err(404, "Gestión no encontrada")
    _check_lock(g, payload.updated_at)

    estado_anterior = g.estado
    now = now_utc()

    # nro_expediente: None=conservar, ""=NULL, valor=setear
    if payload.nro_expediente is None:
        nuevo_nro = g.nro_expediente
    else:
        s = str(payload.nro_expediente).strip()
        nuevo_nro = s or None

    nueva_fecha_ingreso = payload.fecha_ingreso or g.fecha_ingreso

    nuevo_departamento = g.departamento if payload.departamento is None else str(payload.departamento).strip()
    if nuevo_departamento == "":
        _err(400, "Departamento no puede quedar vacío")
    nueva_localidad = g.localidad if payload.localidad is None else str(payload.localidad).strip()
    if nueva_localidad == "":
        _err(400, "Localidad no puede quedar vacía")

    geo = await _geo_lookup(db, nuevo_departamento, nueva_localidad)
    if geo is None:
        _err(400, "Departamento/Localidad inválidos (no existen en geo_localidades)")

    old = {
        "nro_expediente": g.nro_expediente,
        "fecha_ingreso": iso(g.fecha_ingreso),
        "departamento": g.departamento,
        "localidad": g.localidad,
    }

    g.estado = payload.nuevo_estado
    g.fecha_estado = now
    g.derivado_a_id = payload.derivado_a if payload.derivado_a is not None else g.derivado_a_id
    # E2: `acciones_implementadas` se persiste en la gestión (antes sólo quedaba en el evento)
    if payload.acciones_implementadas is not None:
        g.acciones_implementadas = payload.acciones_implementadas
    # E1: catálogos + Ok Gob/Min seteables al cambiar estado (aditivo, sólo si vienen)
    if payload.categoria_id is not None:
        g.categoria_id = payload.categoria_id
    if payload.programa_id is not None:
        g.programa_id = payload.programa_id
    if payload.area_id is not None:
        g.area_id = payload.area_id
    if payload.ok_gobernador is not None:
        g.ok_gobernador = payload.ok_gobernador
    if payload.ok_ministro is not None:
        g.ok_ministro = payload.ok_ministro
    g.nro_expediente = nuevo_nro
    g.fecha_ingreso = nueva_fecha_ingreso
    g.departamento = nuevo_departamento
    g.localidad = nueva_localidad
    g.geo_id = geo["id_geo"]
    # RE-9: fecha_finalizacion sigue al estado (el sistema viejo nunca la seteaba)
    if payload.nuevo_estado == "FINALIZADA":
        g.fecha_finalizacion = date.today()
    elif estado_anterior == "FINALIZADA":
        g.fecha_finalizacion = None
    g.updated_at = now
    g.updated_by = actor.email or actor.uid

    meta = {
        "derivado_a": payload.derivado_a,
        "acciones_implementadas": payload.acciones_implementadas,
        "nro_expediente": nuevo_nro,
        "fecha_ingreso": iso(nueva_fecha_ingreso),
        "departamento": nuevo_departamento,
        "localidad": nueva_localidad,
        "geo_id": geo["id_geo"],
    }
    db.add(_nuevo_evento(
        g.id, actor, "CAMBIO_ESTADO",
        estado_anterior=estado_anterior, estado_nuevo=payload.nuevo_estado,
        comentario=payload.comentario, metadata_json=meta,
    ))

    nuevo = {
        "nro_expediente": nuevo_nro,
        "fecha_ingreso": iso(nueva_fecha_ingreso),
        "departamento": nuevo_departamento,
        "localidad": nueva_localidad,
    }
    for campo in ("nro_expediente", "fecha_ingreso", "departamento", "localidad"):
        if (old[campo] or None) != (nuevo[campo] or None):
            db.add(_nuevo_evento(
                g.id, actor, "ACTUALIZA_DATO",
                estado_anterior=estado_anterior, estado_nuevo=payload.nuevo_estado,
                campo_modificado=campo,
                valor_anterior=None if old[campo] is None else str(old[campo]),
                valor_nuevo=None if nuevo[campo] is None else str(nuevo[campo]),
                comentario=payload.comentario,
                metadata_json={"campo": campo, "valor_anterior": old[campo], "valor_nuevo": nuevo[campo], "estado_contexto": payload.nuevo_estado},
            ))

    await db.flush()
    await audit.log_audit(db, actor=actor, action="CAMBIO_ESTADO", resource_type="privada_gestion", resource_id=g.id, payload={"estado": payload.nuevo_estado})
    return {"ok": True, "id_gestion": g.id, "estado": payload.nuevo_estado}


async def patch_gestion(db: AsyncSession, actor: AuthUser, id_or_legacy: str, payload: GestionUpdate) -> dict:
    g = await _resolve(db, id_or_legacy)
    if g is None:
        _err(404, "Gestión no encontrada")
    _check_lock(g, payload.updated_at)

    data = payload.model_dump(exclude_unset=True, exclude={"updated_at"})
    if ("departamento" in data) or ("localidad" in data):
        dep = data.get("departamento", g.departamento)
        loc = data.get("localidad", g.localidad)
        geo = await _geo_lookup(db, dep, loc)
        if geo is None:
            _err(400, "Departamento/Localidad inválidos (no existen en geo_localidades)")
        g.geo_id = geo["id_geo"]

    now = now_utc()
    cambios = []
    for campo, valor in data.items():
        anterior = getattr(g, campo)
        if (anterior or None) == (valor or None):
            continue
        setattr(g, campo, valor)
        cambios.append((campo, anterior, valor))
        db.add(_nuevo_evento(
            g.id, actor, "ACTUALIZA_DATO", campo_modificado=campo,
            valor_anterior=None if anterior is None else str(anterior),
            valor_nuevo=None if valor is None else str(valor),
            metadata_json={"campo": campo, "valor_anterior": iso(anterior), "valor_nuevo": iso(valor)},
        ))
    g.updated_at = now
    g.updated_by = actor.email or actor.uid
    await db.flush()
    await audit.log_audit(db, actor=actor, action="UPDATE", resource_type="privada_gestion", resource_id=g.id, payload={"campos": [c[0] for c in cambios]})
    return _detail(g)


async def corregir_detalle(db: AsyncSession, actor: AuthUser, id_or_legacy: str, payload: DetalleCorreccion) -> dict:
    """Corrección manual de `detalle` (error de carga) desde el panel general.

    No es un `patch_gestion` más: no dispara ACTUALIZA_DATO ni aparece en el timeline de
    Movimientos — queda como `CORRECCION_DETALLE` únicamente en `priv_gestiones_eventos` +
    `audit_log`, para no confundir a quien lee el historial con un cambio de negocio."""
    g = await _resolve(db, id_or_legacy)
    if g is None:
        _err(404, "Gestión no encontrada")
    _check_lock(g, payload.updated_at)

    anterior = g.detalle
    nuevo = payload.detalle.strip()
    if anterior == nuevo:
        return _detail(g)

    now = now_utc()
    g.detalle = nuevo
    g.updated_at = now
    g.updated_by = actor.email or actor.uid

    db.add(_nuevo_evento(
        g.id, actor, "CORRECCION_DETALLE",
        campo_modificado="detalle", valor_anterior=anterior, valor_nuevo=nuevo,
        comentario="Corrección manual de error de carga (no es un cambio de gestión)",
        metadata_json={"motivo": "correccion_error_carga"},
    ))
    await db.flush()
    await audit.log_audit(
        db, actor=actor, action="CORRECCION_DETALLE", resource_type="privada_gestion", resource_id=g.id,
        payload={"valor_anterior": anterior, "valor_nuevo": nuevo},
    )
    return _detail(g)


async def eliminar_gestion(db: AsyncSession, actor: AuthUser, id_or_legacy: str) -> dict:
    g = await _resolve(db, id_or_legacy)
    if g is None:
        _err(404, "Gestión no encontrada")
    now = now_utc()
    g.deleted_at = now
    g.updated_at = now
    g.updated_by = actor.email or actor.uid
    db.add(_nuevo_evento(
        g.id, actor, "ARCHIVO",
        campo_modificado="is_deleted", valor_anterior="FALSE", valor_nuevo="TRUE",
        comentario="Borrado lógico desde UI", metadata_json={},
    ))
    await db.flush()
    await audit.log_audit(db, actor=actor, action="DELETE", resource_type="privada_gestion", resource_id=g.id)
    return {"ok": True}


# ── resumen territorial (Anexo A2) ─────────────────────────────────────────

def _sort_key(item: dict):
    g = item["gestion"]
    estado = norm(g.get("estado"))
    urg = str(g.get("urgencia") or "").strip().lower()
    if urg == "alta":
        prio = 0
    elif estado not in _CERRADOS:
        prio = 1
    elif estado == "FINALIZADA":
        prio = 2
    else:
        prio = 3
    ref = g.get("fecha_ingreso") or g.get("fecha_estado")
    try:
        ts = datetime.fromisoformat(str(ref)).timestamp() if ref else 0
    except ValueError:
        ts = 0
    return (prio, -ts)


async def _localidad_info(db: AsyncSession, departamento: str, localidad: str) -> dict:
    row = (
        await db.execute(
            select(LocalidadInfo).where(
                func.upper(func.trim(LocalidadInfo.departamento)) == norm(departamento),
                func.upper(func.trim(LocalidadInfo.localidad)) == norm(localidad),
            ).limit(1)
        )
    ).scalar_one_or_none()
    return {
        "departamento": (row.departamento if row else None) or departamento,
        "localidad": (row.localidad if row else None) or localidad,
        "habitantes": row.habitantes if row else None,
        "electores": row.electores if row else None,
        "intendente_jefe_comunal": row.intendente_jefe_comunal if row else None,
        "partido_politico": row.partido_politico if row else None,
        "tipo_localidad": row.tipo_localidad if row else None,
        "color_semaforo": row.color_semaforo if row else None,
        "updated_at": iso(row.updated_at) if row else None,
        "updated_by": row.updated_by if row else None,
    }


def _localidad_info_row(row: LocalidadInfo) -> dict:
    return {
        "departamento": row.departamento,
        "localidad": row.localidad,
        "habitantes": row.habitantes,
        "electores": row.electores,
        "intendente_jefe_comunal": row.intendente_jefe_comunal,
        "partido_politico": row.partido_politico,
        "tipo_localidad": row.tipo_localidad,
        "color_semaforo": row.color_semaforo,
        "updated_at": iso(row.updated_at),
        "updated_by": row.updated_by,
    }


async def listar_localidades_info(db: AsyncSession) -> list[dict]:
    """Todas las filas de `priv_localidades_info` — para el export Excel / impresión
    del Resumen Territorial (evita el N+1 de `GET /localidades-info` de a una)."""
    rows = (
        await db.execute(
            select(LocalidadInfo).order_by(LocalidadInfo.departamento, LocalidadInfo.localidad)
        )
    ).scalars().all()
    return [_localidad_info_row(r) for r in rows]


async def _departamento_info(db: AsyncSession, departamento: str) -> dict:
    row = (
        await db.execute(
            select(DepartamentoInfo).where(
                func.upper(func.trim(DepartamentoInfo.departamento)) == norm(departamento)
            ).limit(1)
        )
    ).scalar_one_or_none()
    return {
        "departamento": (row.departamento if row else None) or departamento,
        "habitantes": row.habitantes if row else None,
        "electores": row.electores if row else None,
        "legislador_departamental": row.legislador_departamental if row else None,
        "partido_politico": row.partido_politico if row else None,
        "legislador_sabana1": row.legislador_sabana1 if row else None,
        "partido_politico_sabana1": row.partido_politico_sabana1 if row else None,
        "legislador_sabana2": row.legislador_sabana2 if row else None,
        "partido_politico_sabana2": row.partido_politico_sabana2 if row else None,
        "updated_at": iso(row.updated_at) if row else None,
        "updated_by": row.updated_by if row else None,
    }


async def resumen_territorial(db: AsyncSession, departamento: str, localidad: str | None) -> dict:
    localidad = (localidad or "").strip()
    solo_depto = not localidad

    conds = [Gestion.deleted_at.is_(None), func.upper(func.trim(Gestion.departamento)) == norm(departamento)]
    if not solo_depto:
        conds.append(func.upper(func.trim(Gestion.localidad)) == norm(localidad))
    gestiones = (await db.execute(select(Gestion).where(and_(*conds)))).scalars().all()
    gids = [g.id for g in gestiones]

    eventos = []
    if gids:
        eventos = (
            await db.execute(
                select(GestionEvento).where(GestionEvento.gestion_id.in_(gids))
                .order_by(GestionEvento.fecha_evento.desc())
            )
        ).scalars().all()
    ev_por_gestion: dict[str, list] = {}
    for e in eventos:
        ev_por_gestion.setdefault(e.gestion_id, []).append(_evento(e, meta_as_str=True))

    if solo_depto:
        territorio = await _departamento_info(db, departamento)
    else:
        territorio = await _localidad_info(db, departamento, localidad)

    abiertas = finalizadas = urgentes = 0
    items = []
    for g in gestiones:
        est = norm(g.estado)
        if est not in _CERRADOS:
            abiertas += 1
        if est == "FINALIZADA":
            finalizadas += 1
        if str(g.urgencia or "").strip().lower() == "alta":
            urgentes += 1
        items.append({"gestion": _resumen_gestion(g), "eventos": ev_por_gestion.get(g.id, [])})

    if solo_depto:
        items.sort(key=lambda it: (norm(it["gestion"].get("localidad")), *_sort_key(it)))
    else:
        items.sort(key=_sort_key)

    return {
        "scope": "departamento" if solo_depto else "localidad",
        "territorio_info": territorio,
        "localidad_info": territorio if not solo_depto else None,
        "departamento_info": territorio if solo_depto else None,
        "metricas": {
            "total_gestiones": len(gestiones),
            "abiertas": abiertas,
            "finalizadas": finalizadas,
            "urgentes": urgentes,
        },
        "gestiones": items,
    }


async def rollup_territorial(db: AsyncSession) -> list[dict]:
    """Rollup global por (departamento, localidad) — Anexo A2, insumo de ADR-016."""
    dep = func.upper(func.trim(Gestion.departamento))
    loc = func.upper(func.trim(Gestion.localidad))
    est = func.upper(func.trim(Gestion.estado))
    rows = (
        await db.execute(
            select(
                dep.label("departamento"),
                loc.label("localidad"),
                func.count().label("total_gestiones"),
                func.count().filter(est.notin_(("FINALIZADA", "ARCHIVADO"))).label("abiertas"),
                func.count().filter(est == "FINALIZADA").label("finalizadas"),
                func.count().filter(func.lower(func.trim(Gestion.urgencia)) == "alta").label("urgentes"),
                func.sum(Gestion.costo_estimado).label("costo_estimado_sum"),
                func.max(Gestion.fecha_estado).label("fecha_estado_max"),
            )
            .where(Gestion.deleted_at.is_(None))
            .group_by(dep, loc)
            .order_by(dep, loc)
        )
    ).all()
    return [
        {
            "departamento": r.departamento,
            "localidad": r.localidad,
            "total_gestiones": int(r.total_gestiones),
            "abiertas": int(r.abiertas),
            "finalizadas": int(r.finalizadas),
            "urgentes": int(r.urgentes),
            "costo_estimado_sum": as_float(r.costo_estimado_sum),
            "fecha_estado_max": iso(r.fecha_estado_max),
        }
        for r in rows
    ]


# ── localidades-info (GET / PUT) ──────────────────────────────────────────

async def get_localidad_info(db: AsyncSession, departamento: str, localidad: str) -> dict:
    return await _localidad_info(db, departamento, localidad)


async def put_localidad_info(db: AsyncSession, actor: AuthUser, payload: LocalidadInfoUpsert) -> dict:
    geo = await _geo_lookup(db, payload.departamento, payload.localidad)
    if geo is None:
        _err(400, "Departamento/Localidad inválidos (no existen en geo_localidades)")
    row = (
        await db.execute(
            select(LocalidadInfo).where(
                func.upper(func.trim(LocalidadInfo.departamento)) == norm(payload.departamento),
                func.upper(func.trim(LocalidadInfo.localidad)) == norm(payload.localidad),
            ).limit(1)
        )
    ).scalar_one_or_none()
    now = now_utc()
    actor_id = actor.email or actor.uid or ""
    if row is None:
        row = LocalidadInfo(departamento=payload.departamento, localidad=payload.localidad, created_at=now, created_by=actor_id)
        db.add(row)
    # el viejo solo persiste estos 4 campos
    row.habitantes = payload.habitantes
    row.electores = payload.electores
    row.intendente_jefe_comunal = payload.intendente_jefe_comunal
    row.partido_politico = payload.partido_politico
    row.updated_at = now
    row.updated_by = actor_id
    await db.flush()
    await audit.log_audit(db, actor=actor, action="UPDATE", resource_type="privada_localidad_info", resource_id=f"{norm(payload.departamento)}|{norm(payload.localidad)}")
    return await _localidad_info(db, payload.departamento, payload.localidad)


async def get_departamento_info(db: AsyncSession, departamento: str) -> dict:
    return await _departamento_info(db, departamento)
