"""Resolución de localidades contra el padrón de svc-vivienda en sync-time
(ADR-024, spec-normalizacion-localidades.md §4.5)."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp import sync as atp_sync
from app.atp.models import AtpCompromiso
from app.config import settings

HEADERS_BD = [
    " ", "DEPARTAMENTO", "LOCALIDAD", "Ministerio", "Fecha de anuncio",
    "Nro. Expediente", "Derivado", "Monto", "Destino", "SALDO ATP",
]
ROW = [
    "1", "Juárez Celman", "Paso Del Durazno", "Gobierno", "19/09/2026", "",
    False, "150000000", "ADOQUINADO", "0",
]


def _mock_sheet(rows):
    return patch("app.integrations.google_sheets.get_values", new=AsyncMock(return_value=rows))


@pytest.fixture(autouse=True)
def _flag_on():
    prev_enabled = settings.resolver_localidades_enabled
    prev_url = settings.svc_vivienda_internal_url
    settings.resolver_localidades_enabled = True
    settings.svc_vivienda_internal_url = "https://svc-vivienda.example"
    yield
    settings.resolver_localidades_enabled = prev_enabled
    settings.svc_vivienda_internal_url = prev_url


@pytest.mark.asyncio
async def test_sync_persiste_id_geo_resuelto(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW]):
        with patch(
            "app.atp.sync.geo_resolver.resolver_localidades", new=AsyncMock(return_value=[("443", "manual")]),
        ) as mock_resolver:
            await atp_sync.sync_from_sheet(db_session)

    mock_resolver.assert_awaited_once_with([("Juárez Celman", "Paso Del Durazno")])
    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    assert compromiso.id_geo == "443"
    assert compromiso.match_tipo == "manual"


@pytest.mark.asyncio
async def test_sync_no_aborta_si_falla_la_resolucion(db_session: AsyncSession):
    with _mock_sheet([HEADERS_BD, ROW]):
        with patch(
            "app.integrations.geo_resolver.httpx.AsyncClient",
            side_effect=RuntimeError("timeout"),
        ):
            resultado = await atp_sync.sync_from_sheet(db_session)

    assert resultado.filas_insertadas == 1
    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    assert compromiso.id_geo is None
    assert compromiso.match_tipo is None


@pytest.mark.asyncio
async def test_flag_apagado_no_llama_al_resolver(db_session: AsyncSession):
    settings.resolver_localidades_enabled = False
    with _mock_sheet([HEADERS_BD, ROW]):
        with patch("app.integrations.geo_resolver.httpx.AsyncClient") as mock_client:
            await atp_sync.sync_from_sheet(db_session)

    mock_client.assert_not_called()
    compromiso = (await db_session.execute(select(AtpCompromiso))).scalar_one()
    assert compromiso.id_geo is None
