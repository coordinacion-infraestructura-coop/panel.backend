"""CRUD de los 3 catálogos editables (spec-privada-categorias-programas.md / ADR-010).

`id` es client-generated (epoch-ms) — mismo patrón que `viv_cc_estados`. `DELETE` con
guard 409 si el catálogo está referenciado por alguna gestión (no borrada).
"""
import time

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AuthUser
from app.catalogos_editables.models import Area, Categoria, Programa
from app.gestiones.models import Gestion

# nombre público -> (modelo, columna FK en priv_gestiones, code del 409, campos permitidos)
_CATS = {
    "categorias": (Categoria, Gestion.categoria_id, "CATEGORIA_EN_USO", {"label", "orden", "activo", "bg", "text_color"}),
    "programas": (Programa, Gestion.programa_id, "PROGRAMA_EN_USO", {"label", "orden", "activo", "codigo"}),
    "areas": (Area, Gestion.area_id, "AREA_EN_USO", {"label", "orden", "activo", "es_centinela"}),
}


def _cfg(nombre: str):
    cfg = _CATS.get(nombre)
    if cfg is None:
        raise HTTPException(404, f"Catálogo '{nombre}' no existe")
    return cfg


def _row(m) -> dict:
    d = {"id": m.id, "label": m.label, "orden": m.orden, "activo": m.activo}
    if isinstance(m, Categoria):
        d["bg"], d["text_color"] = m.bg, m.text_color
    elif isinstance(m, Programa):
        d["codigo"] = m.codigo
    elif isinstance(m, Area):
        d["es_centinela"] = m.es_centinela
    return d


async def listar(db: AsyncSession, nombre: str, *, incluir_inactivos: bool = False) -> list[dict]:
    model, *_ = _cfg(nombre)
    stmt = select(model)
    if not incluir_inactivos:
        stmt = stmt.where(model.activo.is_(True))
    rows = (await db.execute(stmt.order_by(model.orden, model.label))).scalars().all()
    return [_row(r) for r in rows]


async def crear(db: AsyncSession, actor: AuthUser, nombre: str, data: dict) -> dict:
    model, _fk, _code, campos = _cfg(nombre)
    payload = {k: v for k, v in data.items() if k in campos}
    obj = model(id=int(time.time() * 1000), **payload)
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, {"code": "CODIGO_DUPLICADO", "message": "Ya existe un ítem con ese código"})
    await audit.log_audit(db, actor=actor, action="CREATE", resource_type=f"privada_{nombre}", resource_id=str(obj.id), payload=payload)
    return _row(obj)


async def actualizar(db: AsyncSession, actor: AuthUser, nombre: str, item_id: int, data: dict) -> dict:
    model, _fk, _code, campos = _cfg(nombre)
    obj = (await db.execute(select(model).where(model.id == item_id))).scalar_one_or_none()
    if obj is None:
        raise HTTPException(404, "Ítem no encontrado")
    cambios = {k: v for k, v in data.items() if k in campos and v is not None}
    for k, v in cambios.items():
        setattr(obj, k, v)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, {"code": "CODIGO_DUPLICADO", "message": "Ya existe un ítem con ese código"})
    await audit.log_audit(db, actor=actor, action="UPDATE", resource_type=f"privada_{nombre}", resource_id=str(item_id), payload=cambios)
    return _row(obj)


async def eliminar(db: AsyncSession, actor: AuthUser, nombre: str, item_id: int) -> dict:
    model, fk_col, code, _campos = _cfg(nombre)
    obj = (await db.execute(select(model).where(model.id == item_id))).scalar_one_or_none()
    if obj is None:
        raise HTTPException(404, "Ítem no encontrado")
    en_uso = (
        await db.execute(
            select(func.count()).select_from(Gestion).where(fk_col == item_id, Gestion.deleted_at.is_(None))
        )
    ).scalar_one()
    if en_uso:
        raise HTTPException(409, {"code": code, "message": f"En uso por {en_uso} gestión(es). Desactivalo en vez de borrarlo."})
    await db.delete(obj)
    await db.flush()
    await audit.log_audit(db, actor=actor, action="DELETE", resource_type=f"privada_{nombre}", resource_id=str(item_id), payload={})
    return {"ok": True}
