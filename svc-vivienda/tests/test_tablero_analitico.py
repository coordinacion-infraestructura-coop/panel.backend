"""Tablero analítico de Vivienda, KPIs por snapshot, área responsable y documentación en paneles.

spec-vivienda-tablero-analitico.md v1.0.0 §4. Regla de fixtures: un solo rol por test
(los `client_*` comparten el override global de dependencias).
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordon_cuneta.models import MunicipioCordonCuneta, PedidoCordonCuneta
from app.geo.models import GeoLocalidad
from app.resumen_territorial import aggregations
from app.resumen_territorial.models import ResumenTerritorialSnapshot
from tests.test_checklist_avance_obra import ITEM_ESTADO_NO_APLICA, _medir, no_aplica  # noqa: F401
from tests.test_checklist_tecnico import (  # noqa: F401 — fixtures compartidos
    BASE,
    CC_BASE,
    CH_BASE,
    ITEM_ESTADO_COMPLETO,
    ML_BASE,
    catalogos,
    localidad_ch,
    municipio_cc,
    proyecto_ml,
)

TABLERO = "/api/v1/vivienda/tablero-analitico"
TENDENCIAS = f"{TABLERO}/tendencias"
HOY = date.today()


@pytest_asyncio.fixture
async def municipio_geo(db_session: AsyncSession) -> str:
    """Un municipio de CC vinculado al padrón (con coordenadas) y con una comunicación de supervisión."""
    db_session.add(GeoLocalidad(
        id_geo="9001", departamento="SAN JUSTO", localidad="EL ARAÑADO",
        lat_centro=-31.74, lon_centro=-62.89, activo=True,
    ))
    await db_session.flush()
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid, orden=1, municipio="El Arañado", departamento="San Justo", localidad_id="9001",
        expediente="0423-1/2026", monto=10_000_000,
    ))
    await db_session.flush()
    db_session.add(PedidoCordonCuneta(
        municipio_id=mid, descripcion="Inspección pendiente", fecha_pedido=HOY - timedelta(days=3),
        secretaria="supervision", created_by="sup@test.com",
    ))
    await db_session.flush()
    return mid


# ── GET /tablero-analitico ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tablero_trae_un_expediente_por_entidad_con_padron_y_avance(
    client: AsyncClient, municipio_geo: str, localidad_ch: str, proyecto_ml: str, catalogos: None
):
    await _medir(client, "cc", municipio_geo, str(HOY), 45)
    r = await client.get(TABLERO)
    assert r.status_code == 200, r.text
    data = r.json()
    por_id = {e["entidad_id"]: e for e in data["expedientes"]}
    assert set(por_id) == {municipio_geo, localidad_ch, proyecto_ml}

    cc = por_id[municipio_geo]
    assert cc["programa"] == "cordon_cuneta"
    assert cc["localidad"] == "EL ARAÑADO"          # nombre oficial del padrón (ADR-026)
    assert cc["departamento"] == "SAN JUSTO"
    assert (cc["lat"], cc["lon"]) == (-31.74, -62.89)
    assert cc["avance_obra_pct"] == 45
    assert [h["tipo"] for h in cc["hitos_obra"]] == ["anticipo", "40", "70", "100"]
    assert cc["hitos_obra"][1]["fecha_medicion"] == str(HOY)
    assert cc["ultima_comunicacion"]["texto"] == "Inspección pendiente"  # Admin ve todo

    ch = por_id[localidad_ch]
    assert ch["lat"] is None and ch["avance_obra_pct"] is None and ch["hitos_obra"] is None
    assert data["total_localidades_padron"] >= 1


@pytest.mark.asyncio
async def test_tablero_checklist_descarta_no_aplica(
    client: AsyncClient, localidad_ch: str, no_aplica: None
):
    for item, estado in [(1, ITEM_ESTADO_NO_APLICA), (2, ITEM_ESTADO_NO_APLICA), (3, ITEM_ESTADO_COMPLETO)]:
        assert (await client.patch(f"{BASE}/ch/{localidad_ch}/items/{item}", json={"item_estado_id": estado})).status_code == 200
    exp = next(e for e in (await client.get(TABLERO)).json()["expedientes"] if e["entidad_id"] == localidad_ch)
    assert (exp["checklist_total"], exp["checklist_faltan"], exp["checklist_iniciado"]) == (12, 11, True)


@pytest.mark.asyncio
async def test_tablero_enmascara_comunicacion_de_supervision(
    client_consulta: AsyncClient, municipio_geo: str, catalogos: None
):
    exp = next(e for e in (await client_consulta.get(TABLERO)).json()["expedientes"] if e["entidad_id"] == municipio_geo)
    assert exp["ultima_comunicacion"]["fecha"] == str(HOY - timedelta(days=3))
    assert exp["ultima_comunicacion"]["texto"] is None


@pytest.mark.asyncio
async def test_tablero_tecnico_dgv_accede(client_tecnico_dgv: AsyncClient, municipio_cc: str, catalogos: None):
    assert (await client_tecnico_dgv.get(TABLERO)).status_code == 200


@pytest.mark.asyncio
async def test_tablero_tecnico_dgv_sigue_sin_panel_cc(client_tecnico_dgv: AsyncClient, catalogos: None):
    assert (await client_tecnico_dgv.get(CC_BASE)).status_code == 403


@pytest.mark.asyncio
async def test_tablero_autoridad_accede_sin_secretaria(client_autoridad: AsyncClient, municipio_cc: str):
    assert (await client_autoridad.get(TABLERO)).status_code == 200


@pytest.mark.asyncio
async def test_tablero_operador_de_otra_secretaria_403(client_privada: AsyncClient):
    assert (await client_privada.get(TABLERO)).status_code == 403
    assert (await client_privada.get(TENDENCIAS)).status_code == 403


@pytest.mark.asyncio
async def test_tablero_invitado_403(client_invitado: AsyncClient):
    assert (await client_invitado.get(TABLERO)).status_code == 403


@pytest.mark.asyncio
async def test_tablero_denominador_sale_del_ultimo_snapshot(
    client: AsyncClient, db_session: AsyncSession, municipio_geo: str
):
    db_session.add(ResumenTerritorialSnapshot(
        payload={"localidades": [], "total_localidades_por_departamento": {"SAN JUSTO": 30, "UNIÓN": 25}},
        computed_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()
    data = (await client.get(TABLERO)).json()
    assert data["total_localidades_padron"] == 55
    assert data["total_localidades_por_departamento"] == {"SAN JUSTO": 30, "UNIÓN": 25}


# ── KPIs por área (función pura) ──────────────────────────────────────────────

def test_kpis_por_area():
    ref = date(2026, 10, 15)
    localidades = [
        {"id_geo": "1", "departamento": "A", "localidad": "X", "programas": [
            {"area": "vivienda", "programa": "cordon_cuneta", "checklist_faltan": 3, "monto": 100.0,
             "ultima_comunicacion": {"fecha": "2026-10-01"}},
            {"area": "vivienda", "programa": "cordoba_hogar", "checklist_faltan": 0, "monto": None,
             "ultima_comunicacion": {"fecha": "2026-09-01"}},       # fuera de la ventana de 30 días
            {"area": "privada", "programa": "gestiones", "checklist_faltan": 0, "monto": None},
        ]},
        {"id_geo": "2", "departamento": "B", "localidad": "Y", "programas": [
            {"area": "vivienda", "programa": "cordoba_hogar", "checklist_faltan": 1, "monto": 50.0,
             "ultima_comunicacion": {"fecha": "2026-09-15"}},       # justo en el borde: 30 días
        ]},
    ]
    k = aggregations.kpis_por_area(localidades, ref, {"vivienda": [40, 80]})
    viv = k["vivienda"]
    assert viv["localidades"] == 2
    assert viv["departamentos"] == 2
    assert viv["programas_activos"] == 3
    assert viv["programas_por_programa"] == {"cordon_cuneta": 1, "cordoba_hogar": 2}
    assert viv["items_faltantes"] == 2
    assert viv["comunicaciones_30d"] == 2
    assert viv["monto_total"] == 150.0
    assert viv["avance_obra_promedio"] == 60.0
    assert k["privada"]["programas_activos"] == 1
    assert k["privada"]["avance_obra_promedio"] is None


def test_dia_ar_usa_hora_argentina():
    assert aggregations.dia_ar(datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)) == date(2026, 10, 15)
    assert aggregations.dia_ar(datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)) == date(2026, 10, 16)


@pytest.mark.asyncio
async def test_actualizar_resumen_guarda_kpis_con_avance(
    client: AsyncClient, db_session: AsyncSession, municipio_geo: str, catalogos: None
):
    await _medir(client, "cc", municipio_geo, str(HOY), 30)
    assert (await client.post("/api/v1/resumen-territorial/actualizar")).status_code == 200
    snap = (await db_session.execute(
        ResumenTerritorialSnapshot.__table__.select().order_by(ResumenTerritorialSnapshot.computed_at.desc())
    )).first()
    viv = snap.kpis["vivienda"]
    assert viv["programas_activos"] == 1
    assert viv["comunicaciones_30d"] == 1
    assert viv["avance_obra_promedio"] == 30.0


# ── GET /tendencias ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tendencias_un_punto_por_dia_el_ultimo_y_omite_sin_kpis(
    client: AsyncClient, db_session: AsyncSession
):
    ahora = datetime.now(timezone.utc)
    def snap(momento, kpis):
        db_session.add(ResumenTerritorialSnapshot(payload={"localidades": []}, computed_at=momento, kpis=kpis))

    snap(ahora - timedelta(days=2, hours=1), {"vivienda": {"programas_activos": 1}})
    snap(ahora - timedelta(days=2), {"vivienda": {"programas_activos": 2}})   # mismo día, más tarde
    snap(ahora - timedelta(days=1), None)                                      # sin backfill: se omite
    snap(ahora - timedelta(days=200), {"vivienda": {"programas_activos": 9}})  # fuera del rango
    await db_session.flush()

    puntos = (await client.get(TENDENCIAS, params={"dias": 90})).json()
    assert [p["kpis"]["programas_activos"] for p in puntos] == [2]
    assert puntos[0]["fecha"] == str(aggregations.dia_ar(ahora - timedelta(days=2)))
    assert (await client.get(TENDENCIAS, params={"dias": 400})).status_code == 422


# ── Área responsable del estado (§4.4) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_area_responsable_alta_edicion_y_valor_invalido(client: AsyncClient):
    for base in (CC_BASE, CH_BASE, "/api/v1/vivienda/mi-lugar"):
        r = await client.post(f"{base}/estados", json={
            "label": "En corrección", "bg": "#fff", "text_color": "#000", "orden": 1,
            "area_responsable": "tecnica",
        })
        assert r.status_code == 201, (base, r.text)
        assert r.json()["area_responsable"] == "tecnica"
        eid = r.json()["id"]
        r = await client.patch(f"{base}/estados/{eid}", json={"area_responsable": None})
        assert r.status_code == 200 and r.json()["area_responsable"] is None
        r = await client.patch(f"{base}/estados/{eid}", json={"area_responsable": "legales"})
        assert r.status_code == 422


# ── Documentación en los paneles (§4.5) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_paneles_exponen_documentacion_sin_no_aplica(
    client: AsyncClient, municipio_cc: str, localidad_ch: str, no_aplica: None
):
    for item, estado in [(1, ITEM_ESTADO_NO_APLICA), (3, ITEM_ESTADO_COMPLETO)]:
        await client.patch(f"{BASE}/ch/{localidad_ch}/items/{item}", json={"item_estado_id": estado})
    ch = next(x for x in (await client.get(CH_BASE)).json()["localidades"] if x["id"] == localidad_ch)
    assert (ch["doc_completos"], ch["doc_total"], ch["doc_iniciado"]) == (1, 13, True)

    cc = next(m for m in (await client.get(CC_BASE)).json()["municipios"] if m["id"] == municipio_cc)
    assert (cc["doc_completos"], cc["doc_total"], cc["doc_iniciado"]) == (None, None, False)
