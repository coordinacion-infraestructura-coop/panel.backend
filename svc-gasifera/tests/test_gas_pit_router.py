"""Tests del panel preliminar de solo lectura (spec-sync-gasifera-pit.md §12)."""
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gas_pit.models import GasPitAccionTerritorio, GasPitObra, GasPitObraLocalidad
from tests.conftest import CONSULTA_USER, INVITADO_USER, SIN_GASIFERA_USER


@pytest.fixture
async def obra_gas(db_session: AsyncSession) -> GasPitObra:
    obra = GasPitObra(
        id="obra-1",
        nombre_obra="Red de gas Huanchilla",
        nombre_obra_norm="red de gas huanchilla",
        departamento_norm="juarez celman",
        sub_tipo_obra="E- OBRAS DE GAS",
        estado_obra="OBRA EN EJECUCION",
        departamento="Juárez Celman",
        avance=0.75,
        contrato_base=1000000,
        pit=False,
        sheet_row_number=10,
        last_synced_at=datetime.now(timezone.utc),
    )
    db_session.add(obra)
    await db_session.flush()
    db_session.add(GasPitObraLocalidad(obra_id=obra.id, localidad="Huanchilla"))
    await db_session.flush()
    return obra


@pytest.fixture
async def accion_territorio(db_session: AsyncSession) -> GasPitAccionTerritorio:
    accion = GasPitAccionTerritorio(
        id="accion-1",
        localidad="Huanchilla",
        departamento="Juárez Celman",
        estado="Cumplido",
        monto_inversion_solicitado=500000,
        sheet_row_number=20,
        last_synced_at=datetime.now(timezone.utc),
    )
    db_session.add(accion)
    await db_session.flush()
    return accion


# ── GET /obras ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_obras_devuelve_localidades_y_total(client: AsyncClient, obra_gas):
    r = await client.get("/api/v1/gasifera/obras")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    obra = data["items"][0]
    assert obra["nombre_obra"] == "Red de gas Huanchilla"
    assert obra["localidades"] == ["Huanchilla"]
    assert obra["avance"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_listar_obras_vacio(client: AsyncClient):
    r = await client.get("/api/v1/gasifera/obras")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


# ── GET /acciones-territorio ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_acciones_territorio(client: AsyncClient, accion_territorio):
    r = await client.get("/api/v1/gasifera/acciones-territorio")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["estado"] == "Cumplido"
    assert data["items"][0]["monto_inversion_solicitado"] == 500000


# ── GET /sync-estado ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_estado_null_si_nunca_sincronizo(client: AsyncClient):
    r = await client.get("/api/v1/gasifera/sync-estado")
    assert r.status_code == 200
    assert r.json() is None


# ── Auth: roles y secretaría ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consulta_puede_leer(client: AsyncClient, as_user):
    as_user(CONSULTA_USER)
    r = await client.get("/api/v1/gasifera/obras")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_sin_secretaria_gasifera_devuelve_403(client: AsyncClient, as_user):
    as_user(SIN_GASIFERA_USER)
    r = await client.get("/api/v1/gasifera/obras")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "PERMISO_INSUFICIENTE"


@pytest.mark.asyncio
async def test_invitado_devuelve_403(client: AsyncClient, as_user):
    as_user(INVITADO_USER)
    r = await client.get("/api/v1/gasifera/obras")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sin_token_devuelve_401(client_sin_auth_override: AsyncClient):
    r = await client_sin_auth_override.get("/api/v1/gasifera/obras")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "AUTH_TOKEN_INVALIDO"
