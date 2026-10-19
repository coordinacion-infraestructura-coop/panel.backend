"""Tablero de Gobierno (spec-tablero-gobierno-panel.md §3.3, Etapa 0).

`get_meta` arma lo que necesita la barra común del tablero: las localidades del nomenclador
de Gobierno para los filtros, los años con datos y la frescura de cada fuente. Las secciones
suman sus propias funciones en las etapas siguientes.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.gobierno import sync as gobierno_sync
from app.gobierno.models import ExtGobLocalidad
from app.tablero.schemas import FuenteFrescura, LocalidadFiltro, TableroMetaResponse
from app.transferencias.models import ExtTransferencia, ExtTransferenciaSyncLog

_TIPOS = {"MU": "Municipio", "CO": "Comuna"}
_ETIQUETAS_GOB = {
    gobierno_sync.FUENTE_NOMENCLADOR: "Nomenclador de localidades (Gobierno)",
    gobierno_sync.FUENTE_VISTA: "0. Resumen General - Vista (Gobierno)",
}


async def _localidades(db: AsyncSession) -> list[LocalidadFiltro]:
    filas = (
        await db.execute(
            select(ExtGobLocalidad)
            .where(ExtGobLocalidad.deleted_at.is_(None))
            .order_by(ExtGobLocalidad.departamento_gob, ExtGobLocalidad.nombre_gob)
        )
    ).scalars()
    return [
        LocalidadFiltro(
            id_geo=loc.id_geo,
            codigo_indec=loc.codigo_indec,
            nombre=loc.nombre_gob,
            departamento=loc.departamento_gob,
            tipo=_TIPOS.get(loc.tipo or ""),
        )
        for loc in filas
    ]


async def _anios(db: AsyncSession) -> list[int]:
    """Años con transferencias cargadas, más el año en curso; del más nuevo al más viejo."""
    periodos = (await db.execute(select(ExtTransferencia.periodo).distinct())).scalars()
    anios = {p.year for p in periodos if p is not None}
    anios.add(datetime.now(timezone.utc).year)
    return sorted(anios, reverse=True)


async def _frescura(db: AsyncSession) -> list[FuenteFrescura]:
    fuentes: list[FuenteFrescura] = []

    logs = {log.fuente: log for log in await gobierno_sync.get_sync_estado(db)}
    for fuente, etiqueta in _ETIQUETAS_GOB.items():
        log = logs.get(fuente)
        fuentes.append(
            FuenteFrescura(
                fuente=fuente,
                etiqueta=etiqueta,
                estado=log.estado if log else "sin_datos",
                ultima_corrida=log.corrida_en if log else None,
                detalle=f"{log.filas_upsert} filas" if log else None,
            )
        )

    ultimo_log = (
        await db.execute(
            select(ExtTransferenciaSyncLog).order_by(ExtTransferenciaSyncLog.corrida_en.desc()).limit(1)
        )
    ).scalar_one_or_none()
    ultimo_periodo = (await db.execute(select(func.max(ExtTransferencia.periodo)))).scalar_one_or_none()
    fuentes.append(
        FuenteFrescura(
            fuente="transferencias",
            etiqueta="Transferencias a municipios y comunas (Transparencia)",
            estado="ok" if ultimo_log else "sin_datos",
            ultima_corrida=ultimo_log.corrida_en if ultimo_log else None,
            ultimo_periodo=ultimo_periodo,
        )
    )

    censo = (
        await db.execute(select(func.count()).select_from(ExtGeoCenso).where(ExtGeoCenso.deleted_at.is_(None)))
    ).scalar_one()
    fuentes.append(
        FuenteFrescura(
            fuente="censo_2022",
            etiqueta="Censo 2022 (INDEC)",
            estado="ok" if censo else "sin_datos",
            ultima_corrida=None,
            detalle=f"carga única · {censo} gobiernos locales" if censo else None,
        )
    )
    return fuentes


async def get_meta(db: AsyncSession) -> TableroMetaResponse:
    return TableroMetaResponse(
        localidades=await _localidades(db),
        anios=await _anios(db),
        frescura=await _frescura(db),
    )
