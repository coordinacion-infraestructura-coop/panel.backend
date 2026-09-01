"""El endpoint interno de rollup territorial (ADR-016 / E5a).

No exige JWT — en producción lo protege sólo IAM de Cloud Run. El test verifica
que responde 200 sin usuario inyectado y con la misma forma que
`GET /api/v1/privada/gestiones/rollup-territorial`.
"""
from datetime import date

import pytest

from app.gestiones.models import Gestion

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
