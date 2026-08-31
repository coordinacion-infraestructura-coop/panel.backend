"""KPIs agregados de los 3 paneles (CC/CH/ML) para el Tablero de Programas.

El Tablero (frontend `ProgramasPage.tsx`) los calculaba en el cliente pidiendo los
GET de panel completo de cordon_cuneta/cordoba_hogar/mi_lugar — vedados a TecnicoDGV
(spec-checklist-tecnico-dgv.md §8), el rol al que §9 le exige ver el Tablero. Este
endpoint devuelve solo los agregados, con ROLES_LECTURA_TABLERO.

La lógica replica 1:1 la que hacía el frontend (incl. el match case-insensitive de
labels 'tc' / 'en obra') para que los números no cambien.
"""
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta
from app.mi_lugar.models import ProyectoML


class TableroCC(BaseModel):
    municipios: int
    con_expediente: int
    convenio_firmado: int
    monto: float
    en_obra: int
    en_tc: int


class TableroCH(BaseModel):
    localidades: int
    total_casas: int
    con_ok_gob: int
    con_expediente: int
    monto: float
    en_tc: int


class TableroML(BaseModel):
    total: int
    exp: int
    muni: int
    prov: int
    total_lotes: int
    con_expediente: int
    monto: float


class TableroViviendaResponse(BaseModel):
    cordon_cuneta: TableroCC
    cordoba_hogar: TableroCH
    mi_lugar: TableroML


def _label_id(estados, label: str) -> int | None:
    return next((e.id for e in estados if (e.label or "").strip().lower() == label), None)


async def get_tablero_vivienda(db: AsyncSession) -> TableroViviendaResponse:
    cc_estados = (await db.execute(select(EstadoCordonCuneta))).scalars().all()
    cc_tc = _label_id(cc_estados, "tc")
    cc_obra = _label_id(cc_estados, "en obra")
    cc = (
        await db.execute(
            select(MunicipioCordonCuneta).where(MunicipioCordonCuneta.deleted_at.is_(None))
        )
    ).scalars().all()
    cordon_cuneta = TableroCC(
        municipios=len(cc),
        con_expediente=sum(1 for m in cc if m.expediente),
        convenio_firmado=sum(1 for m in cc if m.ok_gob == "SI"),
        monto=float(sum((m.monto or 0) for m in cc)),
        en_obra=sum(1 for m in cc if cc_obra is not None and m.estado_general == cc_obra),
        en_tc=sum(1 for m in cc if cc_tc is not None and m.estado_general == cc_tc),
    )

    ch_estados = (await db.execute(select(EstadoCordobaHogar))).scalars().all()
    ch_tc = _label_id(ch_estados, "tc")
    ch = (
        await db.execute(
            select(LocalidadCordobaHogar).where(LocalidadCordobaHogar.deleted_at.is_(None))
        )
    ).scalars().all()
    cordoba_hogar = TableroCH(
        localidades=len(ch),
        total_casas=sum((loc.cantidad_casas or 0) for loc in ch),
        con_ok_gob=sum(1 for loc in ch if loc.ok_gob == "SI"),
        con_expediente=sum(1 for loc in ch if loc.expediente),
        monto=float(sum((loc.monto or 0) for loc in ch)),
        en_tc=sum(1 for loc in ch if ch_tc is not None and loc.estado_general == ch_tc),
    )

    ml = (
        await db.execute(select(ProyectoML).where(ProyectoML.deleted_at.is_(None)))
    ).scalars().all()
    mi_lugar = TableroML(
        total=len(ml),
        exp=sum(1 for p in ml if p.tipo == "exp"),
        muni=sum(1 for p in ml if p.tipo == "muni"),
        prov=sum(1 for p in ml if p.tipo == "prov"),
        total_lotes=sum((p.lotes or 0) for p in ml),
        con_expediente=sum(1 for p in ml if p.expediente),
        monto=float(sum((p.monto or 0) for p in ml)),
    )

    return TableroViviendaResponse(
        cordon_cuneta=cordon_cuneta, cordoba_hogar=cordoba_hogar, mi_lugar=mi_lugar
    )
