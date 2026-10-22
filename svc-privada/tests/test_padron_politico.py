"""Padrón político único (ADR-027, docs/files/spec-padron-politico-gobierno-privada.md).
svc-datos-externos se simula parcheando `fetch_padron_combinado`. Datos sintéticos."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.integrations.datos_externos import PadronPoliticoNoDisponible
from app.territorial.models import GeoLocalidad, LocalidadInfo, LocalidadInfoRespaldo

FETCH = "app.territorial.padron_politico.fetch_padron_combinado"
COMBINADO = [
    # Gobierno distinto de Privada: gana Gobierno.
    {"id_geo": "1", "intendente": "INT GOB A", "partido": "PARTIDO G", "origen_intendente": "gobierno", "origen_partido": "gobierno"},
    # Gobierno sin partido: el combinado ya trae el de Privada (igual al actual) -> sin cambio.
    {"id_geo": "2", "intendente": "INT B", "partido": "PARTIDO P", "origen_intendente": "gobierno", "origen_partido": "privada"},
    # Sin fila en Privada pero en el espejo: se crea.
    {"id_geo": "3", "intendente": "INT C", "partido": "PARTIDO G", "origen_intendente": "gobierno", "origen_partido": "gobierno"},
    # Ni fila ni espejo: se informa.
    {"id_geo": "9", "intendente": "INT X", "partido": "PARTIDO G", "origen_intendente": "gobierno", "origen_partido": "gobierno"},
]


async def _cargar(db):
    db.add_all([
        LocalidadInfo(departamento="D1", localidad="L1", id_geo="1", intendente_jefe_comunal="INT PRIV A", partido_politico="PARTIDO P", habitantes=10),
        LocalidadInfo(departamento="D1", localidad="L1 VIEJO", id_geo="1", intendente_jefe_comunal=None, partido_politico="PARTIDO G"),
        LocalidadInfo(departamento="D1", localidad="L2", id_geo="2", intendente_jefe_comunal="INT B", partido_politico="PARTIDO P"),
        LocalidadInfo(departamento="D2", localidad="SIN GEO", id_geo=None, intendente_jefe_comunal="INT Z", partido_politico="Z"),
        GeoLocalidad(id_geo="3", departamento="D2", localidad="L3", activo=True),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_sync_escribe_gobierno_respalda_y_crea(client, db_session):
    await _cargar(db_session)
    with patch(FETCH, new=AsyncMock(return_value=COMBINADO)):
        r = await client.post("/internal/privada/padron-politico/sync")
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["filas_actualizadas"], d["filas_creadas"], d["campos_cambiados"]) == (2, 1, 5)
    assert d["id_geo_sin_espejo"] == ["9"] and d["filas_privada_sin_par_en_gobierno"] == 1

    filas = {f.localidad: f for f in (await db_session.execute(select(LocalidadInfo))).scalars()}
    assert (filas["L1"].intendente_jefe_comunal, filas["L1"].partido_politico) == ("INT GOB A", "PARTIDO G")
    assert filas["L1"].habitantes == 10  # no toca otros campos
    assert filas["L1 VIEJO"].intendente_jefe_comunal == "INT GOB A"  # mismo id_geo, mismo valor
    assert filas["L2"].partido_politico == "PARTIDO P"
    assert (filas["L3"].id_geo, filas["L3"].intendente_jefe_comunal) == ("3", "INT C")
    assert filas["SIN GEO"].intendente_jefe_comunal == "INT Z"

    respaldo = {r.localidad: r for r in (await db_session.execute(select(LocalidadInfoRespaldo))).scalars()}
    assert set(respaldo) == {"L1", "L1 VIEJO"}
    assert respaldo["L1"].intendente_jefe_comunal == "INT PRIV A"

    # Segunda corrida: nada que cambiar y el respaldo sigue con el original.
    with patch(FETCH, new=AsyncMock(return_value=[{**COMBINADO[0], "intendente": "INT GOB A2"}])):
        await client.post("/internal/privada/padron-politico/sync")
    respaldo = {r.localidad: r for r in (await db_session.execute(select(LocalidadInfoRespaldo))).scalars()}
    assert respaldo["L1"].intendente_jefe_comunal == "INT PRIV A"

    listado = (await client.get("/internal/privada/padron-politico")).json()
    l1 = next(f for f in listado if f["localidad"] == "L1")
    assert (l1["intendente"], l1["intendente_respaldo"], l1["respaldado"]) == ("INT GOB A2", "INT PRIV A", True)
    l2 = next(f for f in listado if f["localidad"] == "L2")
    assert (l2["intendente_respaldo"], l2["respaldado"]) == ("INT B", False)


@pytest.mark.asyncio
async def test_dry_run_no_escribe(client, db_session):
    await _cargar(db_session)
    with patch(FETCH, new=AsyncMock(return_value=COMBINADO)):
        d = (await client.post("/internal/privada/padron-politico/sync", params={"dry_run": True})).json()
    assert d["dry_run"] is True and d["filas_actualizadas"] == 2 and d["filas_creadas"] == 1
    filas = {f.localidad: f for f in (await db_session.execute(select(LocalidadInfo))).scalars()}
    assert filas["L1"].intendente_jefe_comunal == "INT PRIV A" and "L3" not in filas
    assert not (await db_session.execute(select(LocalidadInfoRespaldo))).scalars().all()


@pytest.mark.asyncio
async def test_sin_datos_externos_no_toca_nada(client, db_session):
    await _cargar(db_session)
    with patch(FETCH, new=AsyncMock(side_effect=PadronPoliticoNoDisponible("caído"))):
        r = await client.post("/internal/privada/padron-politico/sync")
    assert r.status_code == 502
    fila = (await db_session.execute(select(LocalidadInfo).where(LocalidadInfo.localidad == "L1"))).scalar_one()
    assert fila.intendente_jefe_comunal == "INT PRIV A"


@pytest.mark.asyncio
async def test_fetch_apagado_lanza():
    from app.integrations.datos_externos import fetch_padron_combinado

    with pytest.raises(PadronPoliticoNoDisponible):
        await fetch_padron_combinado()
