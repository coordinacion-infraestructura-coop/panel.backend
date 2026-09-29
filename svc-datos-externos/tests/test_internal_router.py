"""Endpoints internos (IAM-only, sin JWT) — ejercitados vía httpx.AsyncClient
directo, sin override de auth (svc-datos-externos v1 no tiene get_current_user)."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso

FILAS = [
    {"periodo": "2026-07", "tipo": "municipio", "departamento_pdf": "Colón", "nombre_pdf": "Salsipuedes", "concepto": "total", "monto": 1000},
]


@pytest.mark.asyncio
async def test_rollup_territorial_devuelve_lista_vacia_sin_datos(client: AsyncClient):
    resp = await client.get("/internal/datos-externos/rollup-territorial")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_rollup_territorial_incluye_censo_cargado(client: AsyncClient, db_session: AsyncSession):
    db_session.add(ExtGeoCenso(
        id="c1", id_geo="100", codigo_indec="140001", categoria="MU",
        departamento_censo="Colón", localidad_censo="Salsipuedes", poblacion_2022=15000,
    ))
    await db_session.commit()

    resp = await client.get("/internal/datos-externos/rollup-territorial")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id_geo"] == "100"
    assert body[0]["poblacion_2022"] == 15000


@pytest.mark.asyncio
async def test_sync_transferencias_ok(client: AsyncClient):
    with patch("app.transferencias.sync.extract.extract_pdf", return_value=(FILAS, {}, None, [])):
        with patch("app.transferencias.sync.pdf_source.descubrir_links", new=AsyncMock(return_value=["https://x/a.pdf"])):
            with patch("app.transferencias.sync.pdf_source.descargar_pdf", new=AsyncMock(return_value=b"%PDF-fake%")):
                with patch(
                    "app.transferencias.sync.geo_resolver.resolver_localidades",
                    new=AsyncMock(return_value=[(None, None)]),
                ):
                    resp = await client.post(
                        "/internal/datos-externos/transferencias/sync",
                        params={"tipo": "municipio", "periodo": "2026-07-01"},
                    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filas_procesadas"] == 1


@pytest.mark.asyncio
async def test_sync_transferencias_tipo_invalido(client: AsyncClient):
    resp = await client.post(
        "/internal/datos-externos/transferencias/sync",
        params={"tipo": "provincia", "periodo": "2026-07-01"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sync_transferencias_502_si_no_se_encuentra_el_pdf(client: AsyncClient):
    from app.transferencias.pdf_source import DescubrimientoError

    with patch(
        "app.transferencias.sync.pdf_source.descubrir_links",
        new=AsyncMock(side_effect=DescubrimientoError("no se encontró el link")),
    ):
        resp = await client.post(
            "/internal/datos-externos/transferencias/sync",
            params={"tipo": "municipio", "periodo": "2026-07-01"},
        )
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_cargar_manual_ok(client: AsyncClient):
    with patch("app.transferencias.sync.extract.extract_pdf", return_value=(FILAS, {}, None, [])):
        with patch(
            "app.transferencias.sync.geo_resolver.resolver_localidades",
            new=AsyncMock(return_value=[(None, None)]),
        ):
            resp = await client.post(
                "/internal/datos-externos/transferencias/cargar-manual",
                data={"tipo": "municipio", "periodo": "2026-07-01", "disparado_por": "pedro@test.com"},
                files={"archivo": ("Recaudacion-Municipios-Julio-2026.pdf", b"%PDF-fake%", "application/pdf")},
            )
    assert resp.status_code == 200
    assert resp.json()["filas_procesadas"] == 1


@pytest.mark.asyncio
async def test_sync_estado_sin_corridas_devuelve_null(client: AsyncClient):
    resp = await client.get("/internal/datos-externos/transferencias/sync-estado")
    assert resp.status_code == 200
    assert resp.json() is None
