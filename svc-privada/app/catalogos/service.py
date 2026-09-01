"""Catálogos — lectura de priv_cat_* y priv_geo_localidades (paridad con el sistema viejo)."""
from fastapi import HTTPException
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalogos.models import (
    CatCanalOrigen,
    CatCategoriaGeneral,
    CatEstado,
    CatMinisterioAgencia,
    CatTipoGestion,
    CatUrgencia,
)
from app.common import as_float, norm
from app.territorial.models import GeoLocalidad

_SIN_DESC = {"estados": CatEstado, "urgencias": CatUrgencia, "ministerios": CatMinisterioAgencia}
_CON_DESC = {"categorias": CatCategoriaGeneral, "tipos-gestion": CatTipoGestion, "canales-origen": CatCanalOrigen}


async def _catalogo(db: AsyncSession, model, con_desc: bool) -> list[dict]:
    rows = (
        await db.execute(
            select(model).where(model.activo.is_(True)).order_by(model.orden, model.nombre)
        )
    ).scalars().all()
    out = []
    for r in rows:
        d = {"id": r.id, "nombre": r.nombre, "orden": r.orden, "activo": r.activo}
        if con_desc:
            d["descripcion"] = r.descripcion
        out.append(d)
    return out


async def listar(db: AsyncSession, nombre: str) -> list[dict]:
    if nombre in _SIN_DESC:
        return await _catalogo(db, _SIN_DESC[nombre], con_desc=False)
    if nombre in _CON_DESC:
        return await _catalogo(db, _CON_DESC[nombre], con_desc=True)
    raise HTTPException(status_code=404, detail={"code": "CATALOGO_INEXISTENTE", "message": nombre})


async def departamentos(db: AsyncSession) -> list[str]:
    rows = (
        await db.execute(
            select(distinct(GeoLocalidad.departamento))
            .where(GeoLocalidad.departamento.isnot(None), func.trim(GeoLocalidad.departamento) != "")
            .order_by(GeoLocalidad.departamento)
        )
    ).scalars().all()
    return list(rows)


async def localidades(db: AsyncSession, departamento: str) -> list[str]:
    rows = (
        await db.execute(
            select(GeoLocalidad.localidad)
            .where(
                func.upper(func.trim(GeoLocalidad.departamento)) == norm(departamento),
                GeoLocalidad.localidad.isnot(None),
                func.trim(GeoLocalidad.localidad) != "",
            )
            .order_by(GeoLocalidad.localidad)
        )
    ).scalars().all()
    return list(rows)


async def geo(db: AsyncSession, departamento: str, localidad: str) -> dict:
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
        raise HTTPException(
            status_code=400,
            detail="Departamento/Localidad inválidos (no existen en geo_localidades)",
        )
    return {
        "id_geo": row.id_geo,
        "departamento": row.departamento,
        "localidad": row.localidad,
        "lat": as_float(row.lat),
        "lon": as_float(row.lon),
    }
