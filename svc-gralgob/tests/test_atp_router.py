"""Tests del panel preliminar de solo lectura (spec-sync-atp-compromiso-gobernador.md §12)."""
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp.models import AtpCompromiso, AtpCronogramaPago
from tests.conftest import CONSULTA_USER, INVITADO_USER, SIN_GRALGOB_USER


@pytest.fixture
async def compromiso(db_session: AsyncSession) -> AtpCompromiso:
    c = AtpCompromiso(
        id="compromiso-1",
        sheet_row_number=6,
        departamento="Calamuchita",
        localidad="Embalse",
        ministerio_destino="Gobierno",
        fecha_anuncio=date(2026, 9, 19),
        derivado=False,
        monto=150000000,
        destino="Adoquinado",
        saldo_atp=0,
        last_synced_at=datetime.now(timezone.utc),
    )
    db_session.add(c)
    await db_session.flush()
    db_session.add(AtpCronogramaPago(compromiso_id=c.id, periodo=date(2026, 4, 1), monto=-30000000))
    db_session.add(AtpCronogramaPago(compromiso_id=c.id, periodo=date(2026, 5, 1), monto=-30000000))
    await db_session.flush()
    return c


# ── GET /compromisos ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_listar_compromisos_devuelve_total_pagado_y_total(client: AsyncClient, compromiso):
    r = await client.get("/api/v1/gralgob/compromisos")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["localidad"] == "Embalse"
    assert item["monto"] == 150000000
    assert item["total_pagado"] == -60000000


@pytest.mark.asyncio
async def test_listar_compromisos_vacio(client: AsyncClient):
    r = await client.get("/api/v1/gralgob/compromisos")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_listar_compromisos_sin_cronograma_total_pagado_null(client: AsyncClient, db_session: AsyncSession):
    db_session.add(AtpCompromiso(
        id="compromiso-2", sheet_row_number=7, localidad="Villa X", monto=1000,
        derivado=False, last_synced_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()

    r = await client.get("/api/v1/gralgob/compromisos")
    assert r.status_code == 200
    assert r.json()["items"][0]["total_pagado"] is None


# ── GET /sync-estado ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_estado_null_si_nunca_sincronizo(client: AsyncClient):
    r = await client.get("/api/v1/gralgob/sync-estado")
    assert r.status_code == 200
    assert r.json() is None


# ── Auth: roles y secretaría ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consulta_puede_leer(client: AsyncClient, as_user):
    as_user(CONSULTA_USER)
    r = await client.get("/api/v1/gralgob/compromisos")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_sin_secretaria_gralgob_devuelve_403(client: AsyncClient, as_user):
    as_user(SIN_GRALGOB_USER)
    r = await client.get("/api/v1/gralgob/compromisos")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "PERMISO_INSUFICIENTE"


@pytest.mark.asyncio
async def test_invitado_devuelve_403(client: AsyncClient, as_user):
    as_user(INVITADO_USER)
    r = await client.get("/api/v1/gralgob/compromisos")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sin_token_devuelve_401(client_sin_auth_override: AsyncClient):
    r = await client_sin_auth_override.get("/api/v1/gralgob/compromisos")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "AUTH_TOKEN_INVALIDO"
