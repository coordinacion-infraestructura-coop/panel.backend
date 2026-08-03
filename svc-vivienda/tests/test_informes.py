"""Tests del módulo de informes por programa (Cordón Cuneta / Córdoba Hogar).

Dos niveles:
- Unitarios de `app/informes/aggregations.py` (funciones puras, sin DB).
- De integración de los endpoints GET/POST informe (CC y CH comparten el mismo
  motor, así que alcanza con testear ambos programas una vez cada uno más a
  fondo en aggregations).
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, EstadoHistorialCC, MunicipioCordonCuneta
from app.geo.models import GeoLocalidad
from app.informes import aggregations

CC_BASE = "/api/v1/vivienda/cordon-cuneta"
CH_BASE = "/api/v1/vivienda/cordoba-hogar"

CATALOGO = {
    1: {"label": "Sin Iniciar", "bg": "#eee", "text_color": "#000", "orden": 0},
    2: {"label": "En revision tecnica", "bg": "#fef3c7", "text_color": "#92400e", "orden": 1},
}


# ── aggregations.py — unitarios, sin DB ─────────────────────────────────────────

def test_kpis_por_estado_respeta_orden_del_catalogo_y_agrupa_sin_estado():
    entidades = [
        {"estado_general": 2}, {"estado_general": 1}, {"estado_general": None}, {"estado_general": 1},
    ]
    resultado = aggregations.kpis_por_estado(entidades, CATALOGO)
    assert [r["estado_id"] for r in resultado] == [1, 2, None]
    assert resultado[0]["cantidad"] == 2
    assert resultado[1]["cantidad"] == 1
    assert resultado[2] == {"estado_id": None, "cantidad": 1, **aggregations.SIN_ESTADO}


def test_kpis_por_estado_sin_entidades_sin_estado_no_agrega_fila():
    resultado = aggregations.kpis_por_estado([{"estado_general": 1}], CATALOGO)
    assert all(r["estado_id"] is not None for r in resultado)


def test_cobertura_por_departamento_calcula_pct_y_usa_display_name_del_geo():
    entidades = [{"departamento": "CAPITAL"}, {"departamento": "Capital"}, {"departamento": "Colón"}]
    geo = [
        {"departamento": "Capital", "localidad": "Córdoba", "activo": True},
        {"departamento": "Capital", "localidad": "Otra", "activo": True},
        {"departamento": "Colón", "localidad": "Jesús María", "activo": True},
        {"departamento": "Colón", "localidad": "Inactiva", "activo": False},
    ]
    resultado = {r["departamento"]: r for r in aggregations.cobertura_por_departamento(entidades, geo)}
    assert resultado["Capital"]["cantidad"] == 2
    assert resultado["Capital"]["localidades_totales"] == 2
    assert resultado["Capital"]["pct_cobertura"] == 100.0
    # Colón: 1 entidad cubierta, 1 sola localidad activa en el padrón (la otra está inactiva)
    assert resultado["Colón"]["cantidad"] == 1
    assert resultado["Colón"]["localidades_totales"] == 1
    assert resultado["Colón"]["pct_cobertura"] == 100.0


def test_cobertura_por_departamento_sin_geo_para_ese_depto_da_pct_cero():
    entidades = [{"departamento": "Departamento Fantasma"}]
    resultado = aggregations.cobertura_por_departamento(entidades, [])
    assert resultado[0]["localidades_totales"] == 0
    assert resultado[0]["pct_cobertura"] == 0.0


def test_evolucion_temporal_agrupa_por_mes_y_ordena():
    historial = [
        {"created_at": datetime(2026, 7, 5, tzinfo=timezone.utc)},
        {"created_at": datetime(2026, 6, 1, tzinfo=timezone.utc)},
        {"created_at": datetime(2026, 7, 20, tzinfo=timezone.utc)},
    ]
    resultado = aggregations.evolucion_temporal(historial)
    assert resultado == [
        {"mes": "2026-06", "cantidad_cambios": 1},
        {"mes": "2026-07", "cantidad_cambios": 2},
    ]


def test_puntos_mapa_matchea_por_nombre_normalizado_ignora_acentos_y_mayusculas():
    entidades = [{"id": "m1", "nombre": "JESUS MARIA", "departamento": "Colón", "estado_general": 1, "expediente": None, "monto": None}]
    geo = [{"departamento": "colon", "localidad": "Jesús María", "lat_centro": -30.9, "lon_centro": -64.1, "activo": True}]
    puntos = aggregations.puntos_mapa(entidades, geo, CATALOGO)
    assert puntos[0]["lat"] == -30.9
    assert puntos[0]["lon"] == -64.1
    assert puntos[0]["estado_label"] == "Sin Iniciar"


def test_puntos_mapa_sin_match_deja_lat_lon_en_none_sin_romper():
    entidades = [{"id": "m1", "nombre": "Localidad Que No Está En El Padrón", "departamento": "Capital", "estado_general": None, "expediente": None, "monto": None}]
    puntos = aggregations.puntos_mapa(entidades, [], CATALOGO)
    assert puntos[0]["lat"] is None
    assert puntos[0]["lon"] is None
    assert puntos[0]["estado_label"] is None


# ── Endpoints — integración ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def cc_con_geo(db_session: AsyncSession) -> str:
    db_session.add(EstadoCordonCuneta(id=1, label="Sin Iniciar", bg="#eee", text_color="#000", orden=0))
    db_session.add(GeoLocalidad(
        id_geo="g1", departamento="Capital", localidad="Córdoba Capital",
        lat_centro=-31.4, lon_centro=-64.18, activo=True,
    ))
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid, orden=1, municipio="Córdoba Capital", departamento="Capital",
        estado_general=1, monto=1000, cordon_cuneta_ml=500, adoquinado_m2=200,
    ))
    await db_session.flush()
    db_session.add(EstadoHistorialCC(
        municipio_id=mid, campo="ejuridico", estado_anterior_id=None, estado_nuevo_id=1,
        created_at=datetime.now(timezone.utc), created_by="test@test.com",
    ))
    await db_session.flush()
    return mid


@pytest.mark.asyncio
async def test_get_informe_sin_snapshot_previo_devuelve_null(client: AsyncClient):
    resp = await client.get(f"{CC_BASE}/informe")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_actualizar_informe_calcula_y_guarda_snapshot(client: AsyncClient, cc_con_geo: str):
    resp = await client.post(f"{CC_BASE}/informe/actualizar")
    assert resp.status_code == 200
    body = resp.json()
    payload = body["payload"]
    assert payload["programa"] == "cordon_cuneta"
    assert payload["total_entidades"] == 1
    assert payload["monto_total"] == 1000.0
    assert payload["metricas_extra"]["cordon_cuneta_ml_total"] == 500.0
    assert payload["metricas_extra"]["adoquinado_m2_total"] == 200.0
    assert payload["departamentos_cubiertos"] == 1
    assert payload["puntos"][0]["lat"] == -31.4
    assert len(payload["evolucion_temporal"]) == 1
    assert body["computed_by"] == "admin@test.com"


@pytest.mark.asyncio
async def test_get_informe_despues_de_actualizar_devuelve_el_ultimo_snapshot(
    client: AsyncClient, cc_con_geo: str
):
    await client.post(f"{CC_BASE}/informe/actualizar")
    resp = await client.get(f"{CC_BASE}/informe")
    assert resp.status_code == 200
    assert resp.json()["payload"]["total_entidades"] == 1


@pytest.mark.asyncio
async def test_actualizar_informe_denegado_a_consulta(client_consulta: AsyncClient, cc_con_geo: str):
    resp = await client_consulta.post(f"{CC_BASE}/informe/actualizar")
    assert resp.status_code == 403


@pytest_asyncio.fixture
async def ch_localidad(db_session: AsyncSession) -> str:
    db_session.add(EstadoCordobaHogar(id=1, label="Sin Iniciar", bg="#eee", text_color="#000", orden=0))
    lid = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid, orden=1, localidad="Villa Allende", departamento="Colón",
        estado_general=1, monto=2000, cantidad_casas=10,
    ))
    await db_session.flush()
    return lid


@pytest.mark.asyncio
async def test_actualizar_informe_cordoba_hogar(client: AsyncClient, ch_localidad: str):
    resp = await client.post(f"{CH_BASE}/informe/actualizar")
    assert resp.status_code == 200
    payload = resp.json()["payload"]
    assert payload["programa"] == "cordoba_hogar"
    assert payload["total_entidades"] == 1
    assert payload["metricas_extra"]["cantidad_casas_total"] == 10
