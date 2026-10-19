"""Valor fiscal sugerido y valor de referencia de mercado desde IDECOR en Mi
Lugar (docs/files/spec-mi-lugar-valor-fiscal-idecor.md §7). La llamada a
svc-datos-externos se reemplaza por un AsyncMock — ningún test toca la red."""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mi_lugar import valuacion_idecor
from app.mi_lugar.models import NomenclaturaML, ProyectoML, ValuacionIdecorML

BASE = "/api/v1/vivienda/mi-lugar/proyectos"

RESPUESTA_OK = {
    "parcelas": [
        {"nomenclatura": "1604220301275100", "origen": "punto", "tipo_parcela": "URBANO",
         "valuacion": "2401670179.86", "valuacion_tierra": "2401670179.86", "valuacion_mejoras": "0",
         "vigencia_desde": "2025-11-06", "valor_mercado": "17154786999.00", "vut_pesos_m2": "57687.00"},
        {"nomenclatura": "1604220301275001", "origen": "nomenclatura", "tipo_parcela": "URBANO",
         "valuacion": "1446876490.5", "valuacion_tierra": "1446876490.5", "valuacion_mejoras": "0",
         "vigencia_desde": "2025-11-06", "valor_mercado": None},
    ],
    "valor_total": "3848546670.36",
    "valor_tierra": "3848546670.36",
    "valor_mejoras": "0.00",
    "valor_mercado": "17154786999.00",
    "mercado_anio": 2025,
    "mercado_parcelas_sin_valor": 1,
    "vigencia_desde": "2025-11-06",
    "puntos_sin_parcela": [],
    "nomenclaturas_no_encontradas": [],
}

NUEVO = {
    "tipo": "exp",
    "nombre": "VILLA MARIA",
    "localidad_nombre": "Villa María",
    "valor_fiscal": "1000.00",
    "geo_puntos": [{"lat": "-32.400594", "lng": "-63.206245"}],
}


@pytest.fixture
def habilitada():
    with patch.object(valuacion_idecor, "habilitada", return_value=True):
        yield


async def _crear(client: AsyncClient, **extra) -> dict:
    with patch.object(valuacion_idecor, "recalcular_en_segundo_plano", new=AsyncMock()):
        r = await client.post(BASE, json={**NUEVO, **extra})
    assert r.status_code == 201, r.text
    return r.json()


# ─── Nomenclaturas ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alta_normaliza_y_deduplica_nomenclaturas(client: AsyncClient):
    p = await _crear(client, nomenclaturas=["1604-2203-0127-5100", "16042203 01275100", " ", "33"])
    assert p["nomenclaturas"] == ["1604220301275100", "33"]


@pytest.mark.asyncio
async def test_patch_reconcilia_con_soft_delete(client: AsyncClient, db_session: AsyncSession):
    p = await _crear(client, nomenclaturas=["111", "222"])
    with patch.object(valuacion_idecor, "recalcular_en_segundo_plano", new=AsyncMock()):
        r = await client.patch(f"{BASE}/{p['id']}", json={"nomenclaturas": ["222", "333"]})
    assert r.status_code == 200
    assert sorted(r.json()["nomenclaturas"]) == ["222", "333"]
    filas = (await db_session.execute(select(NomenclaturaML).where(NomenclaturaML.proyecto_id == p["id"]))).scalars().all()
    borradas = [f.nomenclatura for f in filas if f.deleted_at is not None]
    assert borradas == ["111"]


@pytest.mark.asyncio
async def test_patch_sin_nomenclaturas_no_las_toca(client: AsyncClient):
    p = await _crear(client, nomenclaturas=["111"])
    with patch.object(valuacion_idecor, "recalcular_en_segundo_plano", new=AsyncMock()) as tarea:
        r = await client.patch(f"{BASE}/{p['id']}", json={"obs": "x"})
    assert r.json()["nomenclaturas"] == ["111"]
    tarea.assert_not_called()


@pytest.mark.asyncio
async def test_nomenclatura_demasiado_larga_422(client: AsyncClient):
    r = await client.post(BASE, json={**NUEVO, "nomenclaturas": ["1" * 31]})
    assert r.status_code == 422


# ─── Disparo en segundo plano ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alta_exp_dispara_recalculo_y_muni_no(client: AsyncClient):
    with patch.object(valuacion_idecor, "recalcular_en_segundo_plano", new=AsyncMock()) as tarea:
        r = await client.post(BASE, json=NUEVO)
        await client.post(BASE, json={**NUEVO, "tipo": "muni"})
    tarea.assert_called_once_with(r.json()["id"])


@pytest.mark.asyncio
async def test_patch_de_puntos_dispara_recalculo(client: AsyncClient):
    p = await _crear(client)
    with patch.object(valuacion_idecor, "recalcular_en_segundo_plano", new=AsyncMock()) as tarea:
        await client.patch(f"{BASE}/{p['id']}", json={"geo_puntos": []})
    tarea.assert_called_once_with(p["id"])


@pytest.mark.asyncio
async def test_segundo_plano_no_hace_nada_si_esta_deshabilitada():
    with patch.object(valuacion_idecor, "AsyncSessionLocal") as sesion:
        await valuacion_idecor.recalcular_en_segundo_plano("x")
    sesion.assert_not_called()


# ─── Recalcular ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recalcular_guarda_resultado_y_no_toca_valor_fiscal(client: AsyncClient, db_session: AsyncSession, habilitada):
    p = await _crear(client, nomenclaturas=["1604220301275001"])
    with patch.object(valuacion_idecor, "consultar_datos_externos", new=AsyncMock(return_value=RESPUESTA_OK)) as consulta:
        r = await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["estado"] == "ok"
    assert Decimal(v["valor_total"]) == Decimal("3848546670.36")
    assert Decimal(v["valor_mercado"]) == Decimal("17154786999.00")
    assert v["mercado_anio"] == 2025
    assert v["cant_parcelas"] == 2
    assert v["parcelas"][1]["origen"] == "nomenclatura"
    puntos, nomenclaturas = consulta.call_args.args
    assert puntos == [{"lat": -32.400594, "lng": -63.206245}]
    assert nomenclaturas == ["1604220301275001"]

    proy = await db_session.get(ProyectoML, p["id"])
    await db_session.refresh(proy)
    assert proy.valor_fiscal == Decimal("1000.00")

    listado = (await client.get(BASE, params={"tipo": "exp"})).json()
    assert Decimal(listado[0]["valuacion_idecor"]["valor_total"]) == Decimal("3848546670.36")


@pytest.mark.asyncio
async def test_error_no_pisa_el_ultimo_resultado_bueno(client: AsyncClient, habilitada):
    p = await _crear(client)
    with patch.object(valuacion_idecor, "consultar_datos_externos", new=AsyncMock(return_value=RESPUESTA_OK)):
        await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    falla = AsyncMock(side_effect=valuacion_idecor.ValuacionNoDisponible("502"))
    with patch.object(valuacion_idecor, "consultar_datos_externos", new=falla):
        r = await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    v = r.json()
    assert v["estado"] == "ok"
    assert Decimal(v["valor_total"]) == Decimal("3848546670.36")
    assert v["ultimo_error_at"] is not None


@pytest.mark.asyncio
async def test_error_sin_resultado_previo_queda_en_error(client: AsyncClient, habilitada):
    p = await _crear(client)
    falla = AsyncMock(side_effect=valuacion_idecor.ValuacionNoDisponible("502"))
    with patch.object(valuacion_idecor, "consultar_datos_externos", new=falla):
        r = await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    assert r.json()["estado"] == "error"
    assert r.json()["valor_total"] is None


@pytest.mark.asyncio
async def test_parcial_y_sin_datos(client: AsyncClient, habilitada):
    p = await _crear(client)
    parcial = {**RESPUESTA_OK, "nomenclaturas_no_encontradas": ["999"]}
    with patch.object(valuacion_idecor, "consultar_datos_externos", new=AsyncMock(return_value=parcial)):
        r = await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    assert r.json()["estado"] == "parcial"
    assert r.json()["nomenclaturas_no_encontradas"] == ["999"]

    with patch.object(valuacion_idecor, "recalcular_en_segundo_plano", new=AsyncMock()):
        await client.patch(f"{BASE}/{p['id']}", json={"geo_puntos": []})
    with patch.object(valuacion_idecor, "consultar_datos_externos", new=AsyncMock()) as consulta:
        r = await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    consulta.assert_not_called()
    assert r.json()["estado"] == "sin_datos"
    assert r.json()["valor_total"] is None


@pytest.mark.asyncio
async def test_recalcular_solo_exp(client: AsyncClient, habilitada):
    p = await _crear(client, tipo="muni")
    r = await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_recalcular_deshabilitado_503(client: AsyncClient):
    p = await _crear(client)
    r = await client.post(f"{BASE}/{p['id']}/valuacion-idecor")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_recalcular_exige_rol_de_escritura(client_consulta: AsyncClient, db_session: AsyncSession, habilitada):
    proy = ProyectoML(tipo="exp", nombre="X", localidad_nombre="X")
    db_session.add(proy)
    await db_session.flush()
    r = await client_consulta.post(f"{BASE}/{proy.id}/valuacion-idecor")
    assert r.status_code == 403


# ─── Cloud Scheduler ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recalcular_todos_solo_exp_no_borrados(db_session: AsyncSession, habilitada):
    for tipo, borrado in (("exp", False), ("exp", True), ("muni", False)):
        db_session.add(ProyectoML(
            tipo=tipo, nombre=f"{tipo}-{borrado}", localidad_nombre="X",
            deleted_at=None if not borrado else __import__("datetime").datetime.now(),
        ))
    await db_session.flush()
    with patch.object(valuacion_idecor, "consultar_datos_externos", new=AsyncMock()) as consulta:
        resumen = await valuacion_idecor.recalcular_todos(db_session)
    assert resumen["proyectos"] == 1
    assert resumen["por_estado"] == {"sin_datos": 1}  # sin puntos ni nomenclaturas: no consulta
    consulta.assert_not_called()
    filas = (await db_session.execute(select(ValuacionIdecorML))).scalars().all()
    assert len(filas) == 1
