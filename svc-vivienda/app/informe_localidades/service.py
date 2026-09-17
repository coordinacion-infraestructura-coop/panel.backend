"""Informe "Localidades por Departamento" — cruce on-the-fly entre el catálogo
geográfico (`viv_geo_localidades`), Cordón Cuneta, Córdoba Hogar y habitantes
(federados desde svc-privada, ADR-012/ADR-016). Sin snapshot: el universo es
chico (~450 localidades) y no hace falta historial de corridas — se recalcula
en cada descarga. Spec: docs/files/spec-informe-localidades-departamento.md
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.cordoba_hogar.models import LocalidadCordobaHogar
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.geo.matching import candidatos_localidad, normalize_name
from app.geo.models import GeoLocalidad
from app.informe_localidades.schemas import LocalidadInformeRow

logger = logging.getLogger(__name__)


def _key(departamento: str | None, localidad: str | None) -> tuple[str, str]:
    return (normalize_name(departamento), normalize_name(localidad))


async def _geo_rows(db: AsyncSession) -> list[GeoLocalidad]:
    result = await db.execute(select(GeoLocalidad).where(GeoLocalidad.activo.is_(True)))
    return list(result.scalars().all())


async def _cc_por_localidad(db: AsyncSession) -> dict[tuple[str, str], MunicipioCordonCuneta]:
    rows = (
        await db.execute(select(MunicipioCordonCuneta).where(MunicipioCordonCuneta.deleted_at.is_(None)))
    ).scalars().all()
    return {_key(m.departamento, m.municipio): m for m in rows}


async def _ch_por_localidad(db: AsyncSession) -> dict[tuple[str, str], LocalidadCordobaHogar]:
    rows = (
        await db.execute(select(LocalidadCordobaHogar).where(LocalidadCordobaHogar.deleted_at.is_(None)))
    ).scalars().all()
    return {_key(loc.departamento, loc.localidad): loc for loc in rows}


def _mint_id_token(audience: str) -> str | None:
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token

        return id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    except Exception as exc:  # noqa: BLE001 — sin credenciales (local/test) es esperable
        logger.warning("informe_localidades: no se pudo mintear ID token para Privada: %s", exc)
        return None


async def fetch_habitantes_privada() -> dict[tuple[str, str], int | None]:
    """Habitantes por cada candidato (departamento, alias-de-localidad) desde
    `priv_localidades_info` (svc-privada), vía el endpoint IAM-only
    `/internal/privada/localidades-habitantes` — mismo patrón fail-open que
    `resumen_territorial.service.fetch_privada_lineas`: cualquier fallo, o el
    flag apagado, devuelve `{}` y el informe se genera igual con
    `cant_habitantes=None` en todas las filas (nunca se inventa un valor).

    Cada fila de `priv_localidades_info` se indexa por TODOS sus candidatos de
    alias (`candidatos_localidad`), no sólo su nombre tal cual — misma lógica
    que usa `services/svc-privada/scripts/cargar_habitantes_censo2022.py` del
    lado del censo, para poder resolver localidades con alias entre
    paréntesis/guion (ej. "SANTA CATALINA (EST. HOLMBERG)")."""
    if not settings.privada_fetch_enabled or not settings.svc_privada_internal_url:
        return {}

    base = settings.svc_privada_internal_url.rstrip("/")
    url = base + settings.privada_localidades_internal_path
    try:
        token = _mint_id_token(base)
        if not token:
            logger.warning(
                "informe_localidades: se llama a Privada SIN ID token (mint falló, audience=%s)", base
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.warning(
                "informe_localidades: Privada respondió %s en %s", resp.status_code, url
            )
            return {}

        rows = resp.json()
        if not isinstance(rows, list):
            return {}
        habitantes: dict[tuple[str, str], int | None] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            depto = normalize_name(r.get("departamento"))
            for loc_key in candidatos_localidad(r.get("localidad")):
                habitantes[(depto, loc_key)] = r.get("habitantes")
        return habitantes
    except Exception as exc:  # noqa: BLE001 — tolerante por diseño
        logger.warning("informe_localidades: fetch de Privada falló (%s): %r", url, exc)
        return {}


def _habitantes_de(g: GeoLocalidad, habitantes: dict[tuple[str, str], int | None]) -> int | None:
    d = normalize_name(g.departamento)
    for loc_key in candidatos_localidad(g.localidad):
        if (d, loc_key) in habitantes:
            return habitantes[(d, loc_key)]
    return None


async def compute_informe(db: AsyncSession) -> list[LocalidadInformeRow]:
    geo = await _geo_rows(db)
    cc_por_loc = await _cc_por_localidad(db)
    ch_por_loc = await _ch_por_localidad(db)
    habitantes = await fetch_habitantes_privada()

    filas = []
    for g in geo:
        k = _key(g.departamento, g.localidad)
        cc = cc_por_loc.get(k)
        ch = ch_por_loc.get(k)
        filas.append(
            LocalidadInformeRow(
                departamento=g.departamento,
                localidad=g.localidad,
                cant_habitantes=_habitantes_de(g, habitantes),
                tiene_cordon_cuneta=cc is not None,
                ml_cordon_cuneta=cc.cordon_cuneta_ml if cc else None,
                tiene_viviendas=ch is not None,
                cantidad_viviendas=ch.cantidad_casas if ch else None,
            )
        )
    filas.sort(key=lambda f: (f.departamento, f.localidad))
    return filas
