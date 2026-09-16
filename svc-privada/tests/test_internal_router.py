"""El endpoint interno de rollup territorial (ADR-016 / E5a) y el de habitantes
por localidad (spec-informe-localidades-departamento.md).

Ninguno exige JWT — en producción los protege sólo IAM de Cloud Run.
"""
from datetime import date

import pytest

from app.gestiones.models import Gestion
from app.territorial.models import LocalidadInfo

_HOY = date(2026, 1, 15)


@pytest.mark.asyncio
async def test_rollup_territorial_interno_sin_auth(client, db_session):
    db_session.add(
        Gestion(
            id="g-int-1",
            estado="INGRESADO",
            urgencia="Alta",
            detalle="obra x",
            departamento="COLON",
            localidad="JESUS MARIA",
            geo_id="1",
            fecha_ingreso=_HOY,
        )
    )
    db_session.add(
        Gestion(
            id="g-int-2",
            estado="FINALIZADA",
            urgencia="Media",
            detalle="obra y",
            departamento="COLON",
            localidad="JESUS MARIA",
            geo_id="1",
            fecha_ingreso=_HOY,
        )
    )
    await db_session.flush()

    # sin dependency_override de get_current_user para este path (no lo usa)
    resp = await client.get("/internal/privada/rollup-territorial")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    fila = next(r for r in body if r["localidad"] == "JESUS MARIA")
    assert fila["total_gestiones"] == 2
    assert fila["abiertas"] == 1
    assert fila["finalizadas"] == 1
    assert fila["urgentes"] == 1
    assert "fecha_estado_max" in fila


@pytest.mark.asyncio
async def test_rollup_territorial_interno_no_bajo_api_v1(client):
    # el path canónico NO existe sin el prefijo interno
    assert (await client.get("/api/v1/internal/privada/rollup-territorial")).status_code == 404


@pytest.mark.asyncio
async def test_localidades_habitantes_interno_sin_auth(client, db_session):
    db_session.add(
        LocalidadInfo(
            departamento="CALAMUCHITA", localidad="AMBOY", habitantes=1000, electores=800,
            intendente_jefe_comunal="X", partido_politico="Y", color_semaforo="verde",
        )
    )
    await db_session.flush()

    # sin dependency_override de get_current_user para este path (no lo usa)
    resp = await client.get("/internal/privada/localidades-habitantes")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["departamento"] == "CALAMUCHITA"
    assert body[0]["localidad"] == "AMBOY"
    assert body[0]["habitantes"] == 1000


@pytest.mark.asyncio
async def test_localidades_habitantes_interno_no_bajo_api_v1(client):
    assert (await client.get("/api/v1/internal/privada/localidades-habitantes")).status_code == 404
