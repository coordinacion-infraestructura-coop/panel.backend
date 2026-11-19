"""Lógica de la planificación de programas por localidad (spec-privada-planificacion-programas.md).

Panel-module pattern de svc-privada (ADR-009): queries inline, sin repository. Cada escritura
va a `priv_audit_log` (`audit.log_audit`, llamado por atributo para que los tests lo parcheen) y,
si cambia un valor de la planilla, también a `priv_plan_historial` en la misma transacción.

Fase 1: catálogos, planilla e historial. Las columnas calculadas desde otros servicios
(en el panel, convenio, visita, coparticipación) llegan en `None` hasta las Fases 2–3; `fuentes`
del listado avisa qué se consultó.
"""
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AuthUser
from app.common import now_utc
from app.planificacion.models import (
    PlanColumna,
    PlanEstado,
    PlanHistorial,
    PlanLocalidad,
    PlanPrioridad,
    PlanPrograma,
)
from app.territorial.models import GeoLocalidad, LocalidadInfo

# Escala de la planilla "Cordón Cuneta OK" (pestañas CELESTE / VERDE-NARANJA / AMARILLO-ROJO), §4.3.
PRIORIDADES_DEFAULT: list[dict[str, Any]] = [
    {"codigo": "1", "nombre": "Prioridad 1", "color_bg": "#B3E5FC", "color_texto": "#01579B", "excluye": False},
    {"codigo": "2", "nombre": "Prioridad 2", "color_bg": "#C8E6C9", "color_texto": "#1B5E20", "excluye": False},
    {"codigo": "3", "nombre": "Prioridad 3", "color_bg": "#FFE0B2", "color_texto": "#E65100", "excluye": False},
    {"codigo": "4", "nombre": "Prioridad 4", "color_bg": "#FFF9C4", "color_texto": "#8D6E00", "excluye": False},
    {"codigo": "5", "nombre": "Prioridad 5", "color_bg": "#FFCDD2", "color_texto": "#B71C1C", "excluye": False},
    {"codigo": "X", "nombre": "Desestimado", "color_bg": "#E0E0E0", "color_texto": "#424242", "excluye": True},
]

# Columnas que trae todo programa nuevo (§4.4); se comportan igual que las agregadas a mano.
COLUMNAS_DEFAULT: list[dict[str, Any]] = [
    {"clave": "anuncio_gobernador", "nombre": "Anuncio del gobernador", "tipo": "si_no"},
    {"clave": "monto_sugerido", "nombre": "Monto sugerido", "tipo": "monto"},
    {"clave": "monto_firmado", "nombre": "Monto firmado", "tipo": "monto"},
    {"clave": "observacion", "nombre": "Observación", "tipo": "texto_largo"},
]

LIMIT_MAX = 1000


# --- helpers -----------------------------------------------------------------------------

def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _norm_txt(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _slug(nombre: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _norm_txt(nombre)).strip("_")
    return (slug or "columna")[:50]


def _naive_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _sello(obj: Any, actor: AuthUser, *, nuevo: bool = False) -> None:
    ahora = now_utc()
    if nuevo:
        obj.created_at, obj.created_by = ahora, actor.email
    obj.updated_at, obj.updated_by = ahora, actor.email


def _programa_out(p: PlanPrograma) -> dict:
    return {
        "id": p.id, "nombre": p.nombre, "area": p.area, "fuente": p.fuente,
        "descripcion": p.descripcion, "orden": p.orden, "activo": p.activo,
    }


def _estado_out(e: PlanEstado) -> dict:
    return {
        "id": e.id, "programa_id": e.programa_id, "nombre": e.nombre, "color_bg": e.color_bg,
        "color_texto": e.color_texto, "orden": e.orden, "eliminado": e.deleted_at is not None,
    }


def _prioridad_out(p: PlanPrioridad) -> dict:
    return {**_estado_out(p), "codigo": p.codigo, "excluye": p.excluye}  # type: ignore[arg-type]


def _columna_out(c: PlanColumna) -> dict:
    return {
        "id": c.id, "programa_id": c.programa_id, "clave": c.clave, "nombre": c.nombre,
        "tipo": c.tipo, "opciones": c.opciones, "orden": c.orden, "visible": c.visible,
        "eliminado": c.deleted_at is not None,
    }


# --- programas ---------------------------------------------------------------------------

async def _programa(db: AsyncSession, programa_id: int) -> PlanPrograma:
    p = (
        await db.execute(
            select(PlanPrograma).where(PlanPrograma.id == programa_id, PlanPrograma.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if p is None:
        raise _err(404, "PROGRAMA_NO_ENCONTRADO", "Programa no encontrado")
    return p


async def _nombre_programa_libre(db: AsyncSession, nombre: str, excepto_id: int | None = None) -> None:
    filas = (
        await db.execute(select(PlanPrograma.id, PlanPrograma.nombre).where(PlanPrograma.deleted_at.is_(None)))
    ).all()
    if any(_norm_txt(n) == _norm_txt(nombre) and i != excepto_id for i, n in filas):
        raise _err(409, "NOMBRE_DUPLICADO", "Ya existe un programa con ese nombre")


async def listar_programas(db: AsyncSession, *, incluir_inactivos: bool = False) -> list[dict]:
    stmt = select(PlanPrograma).where(PlanPrograma.deleted_at.is_(None))
    if not incluir_inactivos:
        stmt = stmt.where(PlanPrograma.activo.is_(True))
    rows = (await db.execute(stmt.order_by(PlanPrograma.area, PlanPrograma.orden, PlanPrograma.nombre))).scalars()
    return [_programa_out(p) for p in rows]


async def crear_programa(db: AsyncSession, actor: AuthUser, data: dict) -> dict:
    data["nombre"] = data["nombre"].strip()
    await _nombre_programa_libre(db, data["nombre"])
    p = PlanPrograma(**data)
    _sello(p, actor, nuevo=True)
    db.add(p)
    await db.flush()
    # Siembra de la escala de prioridades y las columnas por defecto (§4.3, §4.4).
    for i, pr in enumerate(PRIORIDADES_DEFAULT):
        obj = PlanPrioridad(programa_id=p.id, orden=i + 1, **pr)
        _sello(obj, actor, nuevo=True)
        db.add(obj)
    for i, col in enumerate(COLUMNAS_DEFAULT):
        obj = PlanColumna(programa_id=p.id, orden=i + 1, visible=True, **col)
        _sello(obj, actor, nuevo=True)
        db.add(obj)
    await db.flush()
    await audit.log_audit(db, actor=actor, action="CREATE", resource_type="privada_plan_programa", resource_id=str(p.id), payload=data)
    return _programa_out(p)


async def actualizar_programa(db: AsyncSession, actor: AuthUser, programa_id: int, data: dict) -> dict:
    p = await _programa(db, programa_id)
    # Campos NOT NULL: un null explícito no los borra.
    data = {k: v for k, v in data.items() if v is not None or k in ("fuente", "descripcion")}
    if "nombre" in data:
        data["nombre"] = data["nombre"].strip()
        await _nombre_programa_libre(db, data["nombre"], excepto_id=p.id)
    for k, v in data.items():
        setattr(p, k, v)
    _sello(p, actor)
    await db.flush()
    await audit.log_audit(db, actor=actor, action="UPDATE", resource_type="privada_plan_programa", resource_id=str(p.id), payload=data)
    return _programa_out(p)


async def eliminar_programa(db: AsyncSession, actor: AuthUser, programa_id: int) -> dict:
    p = await _programa(db, programa_id)
    p.deleted_at = now_utc()
    _sello(p, actor)
    await db.flush()
    await audit.log_audit(db, actor=actor, action="DELETE", resource_type="privada_plan_programa", resource_id=str(p.id), payload={})
    return {"ok": True}


# --- estados / prioridades / columnas (catálogos por programa) ---------------------------

_CATALOGOS = {
    "estados": (PlanEstado, _estado_out, "privada_plan_estado"),
    "prioridades": (PlanPrioridad, _prioridad_out, "privada_plan_prioridad"),
    "columnas": (PlanColumna, _columna_out, "privada_plan_columna"),
}


async def listar_catalogo(db: AsyncSession, programa_id: int, nombre: str, *, incluir_eliminados: bool = False) -> list[dict]:
    await _programa(db, programa_id)
    model, out, _ = _CATALOGOS[nombre]
    stmt = select(model).where(model.programa_id == programa_id)
    if not incluir_eliminados:
        stmt = stmt.where(model.deleted_at.is_(None))
    rows = (await db.execute(stmt.order_by(model.orden, model.id))).scalars()
    return [out(r) for r in rows]


async def _vivos(db: AsyncSession, model: Any, programa_id: int) -> list[Any]:
    return list(
        (await db.execute(select(model).where(model.programa_id == programa_id, model.deleted_at.is_(None)))).scalars()
    )


async def _item(db: AsyncSession, model: Any, programa_id: int, item_id: int) -> Any:
    obj = (
        await db.execute(
            select(model).where(model.id == item_id, model.programa_id == programa_id, model.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if obj is None:
        raise _err(404, "ITEM_NO_ENCONTRADO", "Ítem no encontrado")
    return obj


async def _validar_unicos(db: AsyncSession, nombre: str, programa_id: int, data: dict, excepto_id: int | None) -> None:
    model = _CATALOGOS[nombre][0]
    otros = [o for o in await _vivos(db, model, programa_id) if o.id != excepto_id]
    if "nombre" in data and any(_norm_txt(o.nombre) == _norm_txt(data["nombre"]) for o in otros):
        raise _err(409, "NOMBRE_DUPLICADO", "Ya existe un ítem con ese nombre en este programa")
    if nombre == "prioridades" and "codigo" in data and any(
        _norm_txt(o.codigo) == _norm_txt(data["codigo"]) for o in otros
    ):
        raise _err(409, "CODIGO_DUPLICADO", "Ya existe una prioridad con ese código en este programa")


def _validar_opciones(tipo: str, opciones: list[str] | None) -> list[str] | None:
    if tipo != "lista":
        return None
    limpias = [o.strip() for o in (opciones or []) if o and o.strip()]
    if not limpias:
        raise _err(422, "OPCIONES_REQUERIDAS", "Una columna de tipo lista necesita al menos una opción")
    return limpias


async def crear_item(db: AsyncSession, actor: AuthUser, programa_id: int, nombre: str, data: dict) -> dict:
    await _programa(db, programa_id)
    model, out, rtype = _CATALOGOS[nombre]
    data["nombre"] = data["nombre"].strip()
    await _validar_unicos(db, nombre, programa_id, data, None)
    if nombre == "columnas":
        data["opciones"] = _validar_opciones(data["tipo"], data.get("opciones"))
        claves = set((await db.execute(select(PlanColumna.clave).where(PlanColumna.programa_id == programa_id))).scalars())
        base = clave = _slug(data["nombre"])
        n = 2
        while clave in claves:  # también contra columnas borradas: sus datos siguen en `valores`
            clave, n = f"{base}_{n}", n + 1
        data["clave"] = clave
    obj = model(programa_id=programa_id, **data)
    _sello(obj, actor, nuevo=True)
    db.add(obj)
    await db.flush()
    await audit.log_audit(db, actor=actor, action="CREATE", resource_type=rtype, resource_id=str(obj.id), payload={"programa_id": programa_id, **data})
    return out(obj)


async def _columna_tiene_datos(db: AsyncSession, col: PlanColumna) -> bool:
    filas = (
        await db.execute(
            select(PlanLocalidad.valores).where(PlanLocalidad.programa_id == col.programa_id, PlanLocalidad.deleted_at.is_(None))
        )
    ).scalars()
    return any((v or {}).get(col.clave) not in (None, "") for v in filas)


async def actualizar_item(db: AsyncSession, actor: AuthUser, programa_id: int, nombre: str, item_id: int, data: dict) -> dict:
    model, out, rtype = _CATALOGOS[nombre]
    obj = await _item(db, model, programa_id, item_id)
    nullables = {"color_bg", "color_texto", "opciones"}
    data = {k: v for k, v in data.items() if v is not None or k in nullables}
    if "nombre" in data:
        data["nombre"] = data["nombre"].strip()
    await _validar_unicos(db, nombre, programa_id, data, item_id)
    if nombre == "columnas":
        tipo = data.get("tipo", obj.tipo)
        if tipo != obj.tipo and await _columna_tiene_datos(db, obj):
            raise _err(409, "COLUMNA_CON_DATOS", "No se puede cambiar el tipo de una columna con datos: creá otra columna")
        if "tipo" in data or "opciones" in data:
            data["opciones"] = _validar_opciones(tipo, data.get("opciones", obj.opciones))
    for k, v in data.items():
        setattr(obj, k, v)
    _sello(obj, actor)
    await db.flush()
    await audit.log_audit(db, actor=actor, action="UPDATE", resource_type=rtype, resource_id=str(item_id), payload=data)
    return out(obj)


async def eliminar_item(db: AsyncSession, actor: AuthUser, programa_id: int, nombre: str, item_id: int) -> dict:
    model, _out, rtype = _CATALOGOS[nombre]
    obj = await _item(db, model, programa_id, item_id)
    # Soft delete: las filas que lo usan lo siguen mostrando "(eliminado)" (§4.3).
    obj.deleted_at = now_utc()
    _sello(obj, actor)
    await db.flush()
    await audit.log_audit(db, actor=actor, action="DELETE", resource_type=rtype, resource_id=str(item_id), payload={})
    return {"ok": True}


# --- planilla ----------------------------------------------------------------------------

def _orden_prioridad(prioridades: dict[int, PlanPrioridad], prioridad_id: int | None) -> tuple:
    p = prioridades.get(prioridad_id) if prioridad_id is not None else None
    if p is None:
        return (2, 0)
    return (1 if p.excluye else 0, p.orden)


async def listar_localidades(
    db: AsyncSession, programa_id: int, *, departamento: str | None = None, limit: int = LIMIT_MAX, offset: int = 0
) -> dict:
    await _programa(db, programa_id)
    stmt = select(GeoLocalidad).where(GeoLocalidad.activo.is_(True))
    if departamento:
        stmt = stmt.where(func.upper(GeoLocalidad.departamento) == departamento.strip().upper())
    geos = list((await db.execute(stmt)).scalars())

    infos: dict[str, LocalidadInfo] = {}
    for info in (await db.execute(select(LocalidadInfo).where(LocalidadInfo.id_geo.is_not(None)))).scalars():
        infos.setdefault(info.id_geo, info)  # type: ignore[arg-type]

    planes = {
        pl.id_geo: pl
        for pl in (
            await db.execute(
                select(PlanLocalidad).where(PlanLocalidad.programa_id == programa_id, PlanLocalidad.deleted_at.is_(None))
            )
        ).scalars()
    }
    cambios = dict(
        (
            await db.execute(
                select(PlanHistorial.id_geo, func.count())
                .where(PlanHistorial.programa_id == programa_id)
                .group_by(PlanHistorial.id_geo)
            )
        ).all()
    )
    prioridades = {p.id: p for p in (await db.execute(select(PlanPrioridad).where(PlanPrioridad.programa_id == programa_id))).scalars()}

    items = []
    for g in geos:
        info = infos.get(g.id_geo)
        pl = planes.get(g.id_geo)
        items.append({
            "id_geo": g.id_geo,
            "departamento": g.departamento,
            "localidad": g.localidad,
            "tipo_localidad": info.tipo_localidad if info else None,
            "habitantes": info.habitantes if info else None,
            "semaforo": info.color_semaforo if info else None,
            "prioridad_id": pl.prioridad_id if pl else None,
            "estado_id": pl.estado_id if pl else None,
            "ok_gobernador": pl.ok_gobernador if pl else None,
            "valores": (pl.valores or {}) if pl else {},
            "updated_at": pl.updated_at if pl else None,
            "cambios": cambios.get(g.id_geo, 0),
        })
    items.sort(key=lambda it: (_orden_prioridad(prioridades, it["prioridad_id"]), it["departamento"], it["localidad"]))
    return {"total": len(items), "items": items[offset: offset + limit], "fuentes": {}}


def _validar_valor(col: PlanColumna, valor: Any) -> Any:
    if valor is None or valor == "":
        return None
    t = col.tipo
    malo = _err(422, "VALOR_INVALIDO", f"Valor inválido para la columna '{col.nombre}' ({t})")
    if t in ("texto", "texto_largo"):
        if not isinstance(valor, str) or (t == "texto" and len(valor) > 500):
            raise malo
        return valor
    if t in ("numero", "monto"):
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise malo
        if t == "monto" and valor < 0:
            raise malo
        return int(valor) if isinstance(valor, float) and valor.is_integer() else valor
    if t == "si_no":
        if not isinstance(valor, bool):
            raise malo
        return valor
    if t == "fecha":
        try:
            return date.fromisoformat(str(valor)).isoformat()
        except ValueError:
            raise malo
    if t == "lista":
        if valor not in (col.opciones or []):
            raise malo
        return valor
    raise malo


def _legible(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    return str(valor)


async def actualizar_localidad(db: AsyncSession, actor: AuthUser, programa_id: int, id_geo: str, data: dict) -> dict:
    await _programa(db, programa_id)
    geo = (
        await db.execute(select(GeoLocalidad).where(GeoLocalidad.id_geo == id_geo, GeoLocalidad.activo.is_(True)))
    ).scalar_one_or_none()
    if geo is None:
        raise _err(404, "LOCALIDAD_NO_ENCONTRADA", "La localidad no está activa en el padrón")

    pl = (
        await db.execute(
            select(PlanLocalidad).where(
                PlanLocalidad.programa_id == programa_id, PlanLocalidad.id_geo == id_geo, PlanLocalidad.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    visto = data.pop("updated_at", None)
    if _naive_utc(visto) != _naive_utc(pl.updated_at if pl else None):
        raise _err(409, "CONFLICTO_EDICION", "Otra persona modificó esta fila. Recargala y volvé a intentar.")

    cambios: list[tuple[str, str | None, str | None]] = []
    nueva = pl is None
    if nueva:
        pl = PlanLocalidad(programa_id=programa_id, id_geo=id_geo, valores={})

    for campo, model in (("prioridad_id", PlanPrioridad), ("estado_id", PlanEstado)):
        if campo not in data:
            continue
        nuevo_id = data[campo]
        if nuevo_id == getattr(pl, campo):
            continue
        nombre_nuevo = None
        if nuevo_id is not None:
            item = (
                await db.execute(
                    select(model).where(model.id == nuevo_id, model.programa_id == programa_id, model.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
            if item is None:
                raise _err(422, "CATALOGO_DE_OTRO_PROGRAMA", f"El {campo.removesuffix('_id')} no pertenece a este programa")
            nombre_nuevo = item.nombre
        anterior = None
        if getattr(pl, campo) is not None:
            anterior = (await db.execute(select(model.nombre).where(model.id == getattr(pl, campo)))).scalar_one_or_none()
        setattr(pl, campo, nuevo_id)
        cambios.append((campo.removesuffix("_id"), anterior, nombre_nuevo))

    if "ok_gobernador" in data and data["ok_gobernador"] != pl.ok_gobernador:
        cambios.append(("ok_gobernador", _legible(pl.ok_gobernador), _legible(data["ok_gobernador"])))
        pl.ok_gobernador = data["ok_gobernador"]

    if data.get("valores"):
        columnas = {c.clave: c for c in await _vivos(db, PlanColumna, programa_id)}
        valores = dict(pl.valores or {})
        for clave, valor in data["valores"].items():
            col = columnas.get(clave)
            if col is None:
                raise _err(422, "COLUMNA_DESCONOCIDA", f"La columna '{clave}' no existe en este programa")
            limpio = _validar_valor(col, valor)
            if limpio == valores.get(clave):
                continue
            cambios.append((clave, _legible(valores.get(clave)), _legible(limpio)))
            if limpio is None:
                valores.pop(clave, None)
            else:
                valores[clave] = limpio
        pl.valores = valores  # reasignar: JSON no detecta mutaciones in-place

    if not cambios:
        return await _fila(db, programa_id, id_geo, pl if not nueva else None)

    _sello(pl, actor, nuevo=nueva)
    if nueva:
        db.add(pl)
    ahora = pl.updated_at
    for campo, antes, despues in cambios:
        db.add(PlanHistorial(
            programa_id=programa_id, id_geo=id_geo, campo=campo, valor_anterior=antes,
            valor_nuevo=despues, usuario=actor.email, fecha=ahora,
        ))
    await db.flush()
    await audit.log_audit(
        db, actor=actor, action="CREATE" if nueva else "UPDATE", resource_type="privada_plan_localidad",
        resource_id=str(pl.id), payload={"programa_id": programa_id, "id_geo": id_geo, "cambios": cambios},
    )
    return await _fila(db, programa_id, id_geo, pl)


async def _fila(db: AsyncSession, programa_id: int, id_geo: str, pl: PlanLocalidad | None) -> dict:
    n = (
        await db.execute(
            select(func.count()).select_from(PlanHistorial).where(
                PlanHistorial.programa_id == programa_id, PlanHistorial.id_geo == id_geo
            )
        )
    ).scalar_one()
    return {
        "id_geo": id_geo,
        "prioridad_id": pl.prioridad_id if pl else None,
        "estado_id": pl.estado_id if pl else None,
        "ok_gobernador": pl.ok_gobernador if pl else None,
        "valores": (pl.valores or {}) if pl else {},
        "updated_at": pl.updated_at if pl else None,
        "cambios": n,
    }


async def historial(db: AsyncSession, programa_id: int, id_geo: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    await _programa(db, programa_id)
    rows = (
        await db.execute(
            select(PlanHistorial)
            .where(PlanHistorial.programa_id == programa_id, PlanHistorial.id_geo == id_geo)
            .order_by(PlanHistorial.fecha.desc(), PlanHistorial.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return [
        {"id": h.id, "campo": h.campo, "valor_anterior": h.valor_anterior, "valor_nuevo": h.valor_nuevo,
         "usuario": h.usuario, "fecha": h.fecha}
        for h in rows
    ]
