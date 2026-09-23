"""Tests del rollup territorial (federación a resumen_territorial de
svc-vivienda, mismo patrón que ADR-016/ADR-021 usaron para Privada/Gasífera)."""
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp import rollup as atp_rollup
from app.atp.models import AtpCompromiso, AtpCronogramaPago


def _compromiso(**kw) -> AtpCompromiso:
    base = dict(
        departamento="Juárez Celman",
        localidad="Huanchilla",
        derivado=False,
        last_synced_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return AtpCompromiso(**base)


@pytest.mark.asyncio
async def test_rollup_agrupa_por_departamento_y_localidad(db_session: AsyncSession):
    # Sin acentos a propósito: SQLite's UPPER()/TRIM() son ASCII-only (a
    # diferencia de Postgres real) — no es parte de lo que este test valida
    # (agrupación), se evita para no acoplar el test a esa diferencia de dialecto.
    c1 = _compromiso(sheet_row_number=1, departamento="Juarez Celman", monto=100000, derivado=False)
    c2 = _compromiso(sheet_row_number=2, departamento="Juarez Celman", monto=200000, derivado=True)
    c3 = _compromiso(sheet_row_number=3, departamento="Punilla", localidad="Cosquin", monto=50000)
    db_session.add_all([c1, c2, c3])
    await db_session.flush()

    rows = await atp_rollup.rollup_territorial(db_session)

    assert len(rows) == 2
    huanchilla = next(r for r in rows if r["localidad"] == "HUANCHILLA")
    assert huanchilla["departamento"] == "JUAREZ CELMAN"
    assert huanchilla["total_compromisos"] == 2
    assert huanchilla["derivados"] == 1
    assert huanchilla["monto_total_sum"] == pytest.approx(300000)

    cosquin = next(r for r in rows if r["localidad"] == "COSQUIN")
    assert cosquin["total_compromisos"] == 1
    assert cosquin["derivados"] == 0


@pytest.mark.asyncio
async def test_rollup_entregado_suma_valor_absoluto_del_cronograma(db_session: AsyncSession):
    c1 = _compromiso(sheet_row_number=1, monto=100000)
    db_session.add(c1)
    await db_session.flush()
    db_session.add_all([
        AtpCronogramaPago(compromiso_id=c1.id, periodo=date(2026, 1, 1), monto=-30000),
        AtpCronogramaPago(compromiso_id=c1.id, periodo=date(2026, 2, 1), monto=-20000),
    ])
    await db_session.flush()

    rows = await atp_rollup.rollup_territorial(db_session)

    assert rows[0]["entregado_sum"] == pytest.approx(50000)


@pytest.mark.asyncio
async def test_rollup_sin_cronograma_entregado_es_cero(db_session: AsyncSession):
    db_session.add(_compromiso(sheet_row_number=1, monto=100000))
    await db_session.flush()

    rows = await atp_rollup.rollup_territorial(db_session)

    assert rows[0]["entregado_sum"] == 0.0


@pytest.mark.asyncio
async def test_rollup_vacio_devuelve_lista_vacia(db_session: AsyncSession):
    assert await atp_rollup.rollup_territorial(db_session) == []


@pytest.mark.asyncio
async def test_rollup_fecha_maxima(db_session: AsyncSession):
    db_session.add_all([
        _compromiso(sheet_row_number=1, fecha_anuncio=date(2026, 1, 10)),
        _compromiso(sheet_row_number=2, fecha_anuncio=date(2026, 3, 5)),
    ])
    await db_session.flush()

    rows = await atp_rollup.rollup_territorial(db_session)
    assert rows[0]["fecha_max"] == "2026-03-05"


# ── Endpoint interno ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_endpoint_rollup_no_requiere_jwt(client: AsyncClient, db_session: AsyncSession):
    db_session.add(_compromiso(sheet_row_number=1, monto=100000))
    await db_session.flush()

    r = await client.get("/internal/atp/rollup-territorial")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["localidad"] == "HUANCHILLA"
