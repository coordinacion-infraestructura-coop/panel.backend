"""Tests del rollup territorial (ADR-017 — federación a resumen_territorial)."""
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gas_pit import rollup as gas_pit_rollup
from app.gas_pit.models import GasPitAccionTerritorio


def _accion(**kw) -> GasPitAccionTerritorio:
    base = dict(
        departamento="Juárez Celman",
        localidad="Huanchilla",
        estado="Cumplido",
        sheet_row_number=1,
        last_synced_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return GasPitAccionTerritorio(**base)


@pytest.mark.asyncio
async def test_rollup_agrupa_por_departamento_y_localidad(db_session: AsyncSession):
    # Sin acentos a propósito: SQLite's UPPER()/TRIM() son ASCII-only (a
    # diferencia de Postgres real, que sí uppercasea Unicode) — no es parte de
    # lo que este test valida (agrupación), se evita para no acoplar el test
    # a esa diferencia de dialecto.
    db_session.add_all([
        _accion(sheet_row_number=1, departamento="Juarez Celman", estado="Cumplido", monto_inversion_solicitado=100, monto_inversion_usd=146000),
        _accion(sheet_row_number=2, departamento="Juarez Celman", estado="En ejecucion", monto_inversion_solicitado=200, monto_inversion_usd=None),
        _accion(sheet_row_number=3, departamento="Punilla", localidad="Cosquin", estado="Pendiente"),
    ])
    await db_session.flush()

    rows = await gas_pit_rollup.rollup_territorial(db_session)

    assert len(rows) == 2
    huanchilla = next(r for r in rows if r["localidad"] == "HUANCHILLA")
    assert huanchilla["departamento"] == "JUAREZ CELMAN"
    assert huanchilla["total_acciones"] == 2
    assert huanchilla["cumplidas"] == 1
    assert huanchilla["en_curso"] == 1
    assert huanchilla["monto_solicitado_sum"] == pytest.approx(300)
    assert huanchilla["monto_usd_sum"] == pytest.approx(146000)

    cosquin = next(r for r in rows if r["localidad"] == "COSQUIN")
    assert cosquin["total_acciones"] == 1
    assert cosquin["cumplidas"] == 0
    assert cosquin["en_curso"] == 1


@pytest.mark.asyncio
async def test_rollup_normaliza_mayusculas_y_espacios_en_estado(db_session: AsyncSession):
    db_session.add(_accion(estado="  cumplido  "))
    await db_session.flush()

    rows = await gas_pit_rollup.rollup_territorial(db_session)

    assert rows[0]["cumplidas"] == 1
    assert rows[0]["en_curso"] == 0


@pytest.mark.asyncio
async def test_rollup_vacio_devuelve_lista_vacia(db_session: AsyncSession):
    assert await gas_pit_rollup.rollup_territorial(db_session) == []


@pytest.mark.asyncio
async def test_rollup_fecha_maxima(db_session: AsyncSession):
    db_session.add_all([
        _accion(sheet_row_number=1, fecha=date(2026, 1, 10)),
        _accion(sheet_row_number=2, fecha=date(2026, 3, 5)),
    ])
    await db_session.flush()

    rows = await gas_pit_rollup.rollup_territorial(db_session)
    assert rows[0]["fecha_max"] == "2026-03-05"


# ── Endpoint interno ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_endpoint_rollup_no_requiere_jwt(client: AsyncClient, db_session: AsyncSession):
    db_session.add(_accion())
    await db_session.flush()

    r = await client.get("/internal/gasifera/rollup-territorial")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["localidad"] == "HUANCHILLA"
