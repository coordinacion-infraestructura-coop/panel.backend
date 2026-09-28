"""Resolución de localidades contra el padrón de svc-vivienda en sync-time
(ADR-024, spec-normalizacion-localidades.md §4.5)."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gas_pit import sync as gas_pit_sync
from app.gas_pit.models import GasPitAccionTerritorio, GasPitObraLocalidad

MATRIZ_HEADERS = ["NOMBRE DE OBRA", "SUB-TIPO DE OBRA", "DEPARTAMENTO", "LOCALIDAD"]
ROW_OBRA = [
    "PROVISION DE GAS VIRTUAL A HUANCHILLA", "E- OBRAS DE GAS", "JUAREZ CELMAN", "TANTI - EL DURAZNO",
]

ACCIONES_HEADERS = [
    "Fecha", "Departamento", "Localidad", "Ministerio", "Área", "",
    "ID_ACCION", "Acción", "Detalle de la acción", "Estado",
    "Monto Inversión solicitado", "Comentarios", "Monto Inversión USD",
    "ALERTA_LOCALIDAD", "DEPTO_SUGERIDO",
]
ROW_ACCION = [
    "01/03/2026", "Juárez Celman", "Huanchilla", "Cooperativas y mutuales",
    "Secretaría Gas", "", "A-1", "Red de gas", "Segunda etapa red de gas",
    "Cumplido", "1000000", "Inaugurado", "", "OK", "",
]


def _mock_sheet(matriz_rows, acciones_rows):
    async def fake_get_values(spreadsheet_id, range_name):
        return matriz_rows if range_name.startswith("MATRIZ") else acciones_rows

    return patch("app.integrations.google_sheets.get_values", new=AsyncMock(side_effect=fake_get_values))


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
    with _mock_sheet([MATRIZ_HEADERS, ROW_OBRA], [ACCIONES_HEADERS, ROW_ACCION]):
        with patch(
            "app.gas_pit.sync.geo_resolver.resolver_localidades", new=AsyncMock(),
        ) as mock_resolver:
            # 2 localidades de la obra (split por " - ") + 1 acción → 3 items en batch
            mock_resolver.return_value = [("158", "alias"), ("443", "exacto"), ("92", "manual")]
            await gas_pit_sync.sync_from_sheet(db_session)

    mock_resolver.assert_awaited_once()
    items_llamados = mock_resolver.await_args.args[0]
    assert len(items_llamados) == 3

    locs = (await db_session.execute(select(GasPitObraLocalidad))).scalars().all()
    assert {(l.localidad, l.id_geo, l.match_tipo) for l in locs} == {
        ("TANTI", "158", "alias"), ("EL DURAZNO", "443", "exacto"),
    }
    accion = (await db_session.execute(select(GasPitAccionTerritorio))).scalar_one()
    assert accion.id_geo == "92"
    assert accion.match_tipo == "manual"


@pytest.mark.asyncio
async def test_sync_no_aborta_si_falla_la_resolucion(db_session: AsyncSession):
    """Best-effort real (no mockeado a nivel de función): un fallo de red
    hacia svc-vivienda no debe frenar el sync ni dejar filas sin insertar —
    quedan con id_geo/match_tipo en None."""
    with _mock_sheet([MATRIZ_HEADERS], [ACCIONES_HEADERS, ROW_ACCION]):
        with patch(
            "app.integrations.geo_resolver.httpx.AsyncClient",
            side_effect=RuntimeError("timeout"),
        ):
            resultado = await gas_pit_sync.sync_from_sheet(db_session)

    assert resultado.filas_insertadas == 1
    accion = (await db_session.execute(select(GasPitAccionTerritorio))).scalar_one()
    assert accion.id_geo is None
    assert accion.match_tipo is None


@pytest.mark.asyncio
async def test_flag_apagado_no_llama_al_resolver(db_session: AsyncSession):
    settings.resolver_localidades_enabled = False
    with _mock_sheet([MATRIZ_HEADERS], [ACCIONES_HEADERS, ROW_ACCION]):
        with patch("app.integrations.geo_resolver.httpx.AsyncClient") as mock_client:
            await gas_pit_sync.sync_from_sheet(db_session)

    mock_client.assert_not_called()
    accion = (await db_session.execute(select(GasPitAccionTerritorio))).scalar_one()
    assert accion.id_geo is None
