"""Tests del módulo Resumen Territorial.

Dos niveles:
- Unitarios de `app/resumen_territorial/aggregations.py` (funciones puras, sin DB).
- Integración de los endpoints GET/POST `/api/v1/resumen-territorial`, incluida la
  regla de visibilidad por área/rol y las líneas de Privada (mockeadas).
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico.models import ChecklistItem, ChecklistTecnico
from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta, PedidoCordonCuneta
from app.geo.models import GeoLocalidad
from app.mi_lugar.models import EstadoML, ProyectoML
from app.resumen_territorial import aggregations
from app.resumen_territorial.schemas import ResumenTerritorialPayload
from app.resumen_territorial.service import filtrar_por_visibilidad

BASE = "/api/v1/resumen-territorial"


# ── aggregations.py — unitarios, sin DB ──────────────────────────────────────

def test_items_faltantes_sin_filas_es_no_iniciado():
    total, faltan, labels, iniciado = aggregations.items_faltantes([], "cc")
    assert total == 19  # CC: 9 ítems + 10 sub-ítems del ítem 4
    assert faltan == 19
    assert labels == []
    assert iniciado is False


def test_items_faltantes_cuenta_los_no_completos_y_trae_labels():
    rows = [
        {"item_num": 1, "sub_item_num": None, "valor": "completo"},
        {"item_num": 2, "sub_item_num": None, "valor": "sin_presentar"},
        {"item_num": 3, "sub_item_num": None, "valor": "a_corregir"},
    ]
    total, faltan, labels, iniciado = aggregations.items_faltantes(rows, "ch")
    assert total == 14
    assert faltan == 2
    assert iniciado is True
    assert "Matrícula de cada lote" in labels  # ítem 2 de CH


def test_items_faltantes_totales_por_programa():
    assert aggregations.items_faltantes([], "cc")[0] == 19
    assert aggregations.items_faltantes([], "ch")[0] == 14
    assert aggregations.items_faltantes([], "ml")[0] == 20  # 14 ítems + 6 sub-ítems del ítem 14


def test_ultima_comunicacion_vacia_es_none():
    assert aggregations.ultima_comunicacion([]) is None


def test_ultima_comunicacion_elige_la_mas_reciente_por_fecha_y_created_at():
    rows = [
        {"fecha_pedido": date(2026, 8, 1), "created_at": datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
         "descripcion": "vieja", "secretaria": None, "created_by": "a@a", "created_by_nombre": None},
        {"fecha_pedido": date(2026, 8, 12), "created_at": datetime(2026, 8, 12, 8, tzinfo=timezone.utc),
         "descripcion": "nueva", "secretaria": "infraestructura", "created_by": "b@b", "created_by_nombre": "Beto"},
        {"fecha_pedido": date(2026, 8, 12), "created_at": datetime(2026, 8, 12, 7, tzinfo=timezone.utc),
         "descripcion": "mismo dia, antes", "secretaria": None, "created_by": "c@c", "created_by_nombre": None},
    ]
    uc = aggregations.ultima_comunicacion(rows)
    assert uc["texto"] == "nueva"
    assert uc["area"] == "infraestructura"
    assert uc["autor"] == "Beto"


def test_agrupar_por_localidad_une_por_nombre_normalizado_y_usa_grafia_del_geo():
    geo = [{"departamento": "Santa María", "localidad": "Alta Gracia"}]
    lineas = [
        {"departamento": "SANTA MARIA", "nombre_localidad": "ALTA GRACIA",
         "programa": {"area": "vivienda", "programa": "cordon_cuneta", "programa_label": "Cordón Cuneta y Adoquinado"}},
        {"departamento": "santa maria", "nombre_localidad": "alta gracia",
         "programa": {"area": "vivienda", "programa": "cordoba_hogar", "programa_label": "Córdoba Hogar"}},
    ]
    grupos = aggregations.agrupar_por_localidad(lineas, geo)
    assert len(grupos) == 1
    assert grupos[0]["localidad"] == "Alta Gracia"
    assert grupos[0]["departamento"] == "Santa María"
    assert [p["programa"] for p in grupos[0]["programas"]] == ["cordon_cuneta", "cordoba_hogar"]


def test_agrupar_por_localidad_dos_proyectos_ml_en_una_localidad_son_dos_lineas():
    lineas = [
        {"departamento": "Calamuchita", "nombre_localidad": "Villa General Belgrano",
         "programa": {"area": "vivienda", "programa": "mi_lugar", "programa_label": "Mi Lugar", "detalle": "Loteo Norte"}},
        {"departamento": "Calamuchita", "nombre_localidad": "Villa General Belgrano",
         "programa": {"area": "vivienda", "programa": "mi_lugar", "programa_label": "Mi Lugar", "detalle": "Loteo Sur"}},
    ]
    grupos = aggregations.agrupar_por_localidad(lineas, [])
    assert len(grupos) == 1
    assert sorted(p["detalle"] for p in grupos[0]["programas"]) == ["Loteo Norte", "Loteo Sur"]


def test_resumen_privada_estado_y_detalle():
    assert aggregations.resumen_privada_estado({"FINALIZADA": 2, "ARCHIVADO": 1})["label"] == "Finalizadas"
    assert aggregations.resumen_privada_estado({"INGRESADO": 3})["label"] == "En curso"
    assert aggregations.resumen_privada_estado({"INGRESADO": 1, "FINALIZADA": 1})["label"] == "Mixto"
    assert aggregations.detalle_privada({"INGRESADO": 3, "FINALIZADA": 2}) == "5 gestiones · 3 en curso, 2 finalizadas"


# ── filtrar_por_visibilidad — unitario ──────────────────────────────────────

def _payload_demo() -> ResumenTerritorialPayload:
    return ResumenTerritorialPayload(
        generado_para_areas=["vivienda", "privada"],
        total_localidades=1,
        total_programas=3,
        localidades=[{
            "localidad": "Alta Gracia",
            "departamento": "Santa María",
            "programas": [
                {"area": "vivienda", "programa": "cordon_cuneta", "programa_label": "Cordón Cuneta y Adoquinado",
                 "ultima_comunicacion": {"fecha": "2026-08-12", "texto": "Nota interna", "area": "infraestructura"}},
                {"area": "vivienda", "programa": "cordoba_hogar", "programa_label": "Córdoba Hogar"},
                {"area": "privada", "programa": "gestiones", "programa_label": "Gestiones — Sec. Privada"},
            ],
        }],
    )


def test_visibilidad_autoridad_ve_todo_sin_enmascarar():
    out = filtrar_por_visibilidad(_payload_demo(), rol="Autoridad", secretarias=[])
    assert out.total_programas == 3
    assert out.localidades[0].programas[0].ultima_comunicacion.texto == "Nota interna"


def test_visibilidad_operador_vivienda_no_ve_privada_y_enmascara_comunicacion_infra():
    out = filtrar_por_visibilidad(_payload_demo(), rol="Operador", secretarias=["vivienda"])
    areas = [p.area for p in out.localidades[0].programas]
    assert areas == ["vivienda", "vivienda"]
    assert out.localidades[0].programas[0].ultima_comunicacion.texto is None  # enmascarado
    assert out.generado_para_areas == ["vivienda"]


def test_visibilidad_usuario_privada_solo_ve_la_linea_de_privada():
    out = filtrar_por_visibilidad(_payload_demo(), rol="Consulta", secretarias=["privada"])
    assert [p.area for p in out.localidades[0].programas] == ["privada"]


def test_visibilidad_usuario_de_area_sin_servicio_no_ve_nada():
    out = filtrar_por_visibilidad(_payload_demo(), rol="Operador", secretarias=["gasifera"])
    assert out.localidades == []
    assert out.total_localidades == 0


def test_visibilidad_supervision_no_enmascara_comunicaciones():
    out = filtrar_por_visibilidad(_payload_demo(), rol="Operador", secretarias=["vivienda", "supervision"])
    assert out.localidades[0].programas[0].ultima_comunicacion.texto == "Nota interna"


def test_visibilidad_infraestructura_ve_texto_de_comunicaciones_de_infraestructura():
    payload = _payload_demo()
    out = filtrar_por_visibilidad(payload, rol="Operador", secretarias=["vivienda", "infraestructura"])
    assert out.localidades[0].programas[0].ultima_comunicacion.texto == "Nota interna"


# ── Integración — endpoints ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def datos_vivienda(db_session: AsyncSession) -> dict:
    db_session.add_all([
        EstadoCordonCuneta(id=10, label="En obra", bg="#dceffb", text_color="#036aa1", orden=2),
        EstadoCordobaHogar(id=20, label="En análisis", bg="#eaeafe", text_color="#4338ca", orden=1),
        EstadoML(id=30, label="Convenio firmado", bg="#e4f3fa", text_color="#2b6d90", orden=1, tipo="muni"),
        GeoLocalidad(id_geo="g1", departamento="Santa María", localidad="Alta Gracia",
                     lat_centro=-31.65, lon_centro=-64.43, activo=True),
        GeoLocalidad(id_geo="g2", departamento="Calamuchita", localidad="Villa General Belgrano",
                     lat_centro=-31.97, lon_centro=-64.55, activo=True),
    ])
    cc_id = str(uuid.uuid4())
    ml_id_1, ml_id_2 = str(uuid.uuid4()), str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=cc_id, orden=1, municipio="Alta Gracia", departamento="Santa María",
        estado_general=10, ejuridico=10, monto=1000, expediente="EE-1",
    ))
    db_session.add(LocalidadCordobaHogar(
        id=str(uuid.uuid4()), orden=1, localidad="Alta Gracia", departamento="Santa María",
        estado_general=20, monto=2000,
    ))
    db_session.add(ProyectoML(
        id=ml_id_1, tipo="muni", nombre="Loteo Norte", localidad_nombre="Villa General Belgrano",
        departamento="Calamuchita", estado_general=30,
    ))
    db_session.add(ProyectoML(
        id=ml_id_2, tipo="muni", nombre="Loteo Sur", localidad_nombre="Villa General Belgrano",
        departamento="Calamuchita", estado_general=30,
    ))
    await db_session.flush()

    chk_id = str(uuid.uuid4())
    db_session.add(ChecklistTecnico(id=chk_id, programa="cc", entidad_id=cc_id))
    await db_session.flush()
    db_session.add_all([
        ChecklistItem(checklist_id=chk_id, item_num=1, sub_item_num=None, valor="completo"),
        ChecklistItem(checklist_id=chk_id, item_num=2, sub_item_num=None, valor="sin_presentar"),
        ChecklistItem(checklist_id=chk_id, item_num=3, sub_item_num=None, valor="a_corregir"),
    ])
    db_session.add(PedidoCordonCuneta(
        municipio_id=cc_id, descripcion="Se pidió el cómputo métrico.", fecha_pedido=date(2026, 8, 12),
        created_at=datetime(2026, 8, 12, tzinfo=timezone.utc), created_by="op@infra", secretaria="infraestructura",
    ))
    await db_session.flush()
    return {"cc_id": cc_id}


@pytest.mark.asyncio
async def test_get_sin_snapshot_previo_devuelve_null(client: AsyncClient):
    resp = await client.get(BASE)
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_actualizar_calcula_snapshot_de_vivienda(client: AsyncClient, datos_vivienda: dict):
    resp = await client.post(f"{BASE}/actualizar")
    assert resp.status_code == 200
    payload = resp.json()["payload"]
    assert payload["generado_para_areas"] == ["vivienda"]

    locs = {loc["localidad"]: loc for loc in payload["localidades"]}
    assert set(locs) == {"Alta Gracia", "Villa General Belgrano"}

    ag = locs["Alta Gracia"]["programas"]
    assert sorted(p["programa"] for p in ag) == ["cordoba_hogar", "cordon_cuneta"]
    cc = next(p for p in ag if p["programa"] == "cordon_cuneta")
    assert cc["estado_general_label"] == "En obra"
    assert cc["checklist_iniciado"] is True
    assert cc["checklist_total"] == 19
    assert cc["checklist_faltan"] == 2  # ítems 2 y 3 no están 'completo'
    assert cc["ultima_comunicacion"]["texto"] == "Se pidió el cómputo métrico."
    ch = next(p for p in ag if p["programa"] == "cordoba_hogar")
    assert ch["checklist_iniciado"] is False
    assert ch["checklist_faltan"] == 14

    vgb = locs["Villa General Belgrano"]["programas"]
    assert [p["programa"] for p in vgb] == ["mi_lugar", "mi_lugar"]
    assert sorted(p["detalle"] for p in vgb) == ["Loteo Norte", "Loteo Sur"]


@pytest.mark.asyncio
async def test_get_despues_de_actualizar_devuelve_ultimo_snapshot(client: AsyncClient, datos_vivienda: dict):
    await client.post(f"{BASE}/actualizar")
    resp = await client.get(BASE)
    assert resp.status_code == 200
    assert resp.json()["payload"]["total_localidades"] == 2


@pytest.mark.asyncio
async def test_actualizar_denegado_a_consulta_pero_get_permitido(client_consulta: AsyncClient, datos_vivienda: dict):
    assert (await client_consulta.post(f"{BASE}/actualizar")).status_code == 403
    assert (await client_consulta.get(BASE)).status_code == 200


@pytest.mark.asyncio
async def test_invitado_no_puede_leer(client_invitado: AsyncClient):
    assert (await client_invitado.get(BASE)).status_code == 403


@pytest.mark.asyncio
async def test_autoridad_ve_el_texto_de_las_comunicaciones(
    client_autoridad: AsyncClient, datos_vivienda: dict
):
    await client_autoridad.post(f"{BASE}/actualizar")
    payload = (await client_autoridad.get(BASE)).json()["payload"]
    cc = next(
        p for loc in payload["localidades"] for p in loc["programas"] if p["programa"] == "cordon_cuneta"
    )
    assert cc["ultima_comunicacion"]["texto"] == "Se pidió el cómputo métrico."


@pytest.mark.asyncio
async def test_operador_vivienda_ve_su_area_con_comunicacion_infra_enmascarada(
    client_operador: AsyncClient, datos_vivienda: dict
):
    await client_operador.post(f"{BASE}/actualizar")
    payload = (await client_operador.get(BASE)).json()["payload"]
    programas = [p["programa"] for loc in payload["localidades"] for p in loc["programas"]]
    assert set(programas) == {"cordon_cuneta", "cordoba_hogar", "mi_lugar"}
    cc = next(
        p for loc in payload["localidades"] for p in loc["programas"] if p["programa"] == "cordon_cuneta"
    )
    assert cc["ultima_comunicacion"]["texto"] is None  # enmascarado (comunicación de infraestructura)


@pytest.mark.asyncio
async def test_usuario_privada_sin_lineas_de_privada_ve_panel_vacio(
    client_privada: AsyncClient, datos_vivienda: dict
):
    await client_privada.post(f"{BASE}/actualizar")  # fetch de Privada mockeado a [] por conftest
    resp = await client_privada.get(BASE)
    assert resp.status_code == 200
    assert resp.json()["payload"]["localidades"] == []


def _privada_linea(dep: str, loc: str, por_estado: dict) -> dict:
    meta = aggregations.resumen_privada_estado(por_estado)
    return {
        "departamento": dep,
        "nombre_localidad": loc,
        "programa": {
            "area": "privada", "programa": "gestiones",
            "programa_label": aggregations.PROGRAMA_LABEL["gestiones"],
            "entidad_id": None, "detalle": aggregations.detalle_privada(por_estado),
            "estado_general_id": None, "estado_general_label": meta["label"],
            "estado_general_bg": meta["bg"], "estado_general_text_color": meta["text_color"],
            "subestados": None, "checklist_total": 0, "checklist_faltan": 0,
            "checklist_iniciado": False, "checklist_faltantes": [],
            "ultima_comunicacion": {"fecha": "2026-08-20", "texto": None, "area": "privada", "autor": None},
            "monto": None, "expediente": None,
            "privada_conteos": {"por_estado": por_estado, "total": sum(por_estado.values())},
        },
    }


@pytest.mark.asyncio
async def test_lineas_de_privada_entran_en_el_snapshot_y_respetan_visibilidad(
    client: AsyncClient, datos_vivienda: dict
):
    privada = [_privada_linea("Santa María", "Alta Gracia", {"INGRESADO": 3, "FINALIZADA": 2})]
    with patch(
        "app.resumen_territorial.service.fetch_privada_lineas", new=AsyncMock(return_value=privada)
    ):
        resp = await client.post(f"{BASE}/actualizar")
    assert resp.status_code == 200
    assert "privada" in resp.json()["payload"]["generado_para_areas"]

    # Admin ve el payload completo: Alta Gracia con cc + ch + privada
    full = ResumenTerritorialPayload.model_validate((await client.get(BASE)).json()["payload"])
    admin_ag = next(loc for loc in full.localidades if loc.localidad == "Alta Gracia")
    assert sorted(p.area for p in admin_ag.programas) == ["privada", "vivienda", "vivienda"]
    priv_line = next(p for p in admin_ag.programas if p.area == "privada")
    assert priv_line.programa_label == "Gestiones — Sec. Privada"
    assert priv_line.privada_conteos.total == 5

    # Filtrado por visibilidad (función pura) sobre el mismo payload:
    op_view = filtrar_por_visibilidad(full, rol="Operador", secretarias=["vivienda"])
    op_ag = next(loc for loc in op_view.localidades if loc.localidad == "Alta Gracia")
    assert all(p.area == "vivienda" for p in op_ag.programas)

    priv_view = filtrar_por_visibilidad(full, rol="Consulta", secretarias=["privada"])
    priv_ag = next(loc for loc in priv_view.localidades if loc.localidad == "Alta Gracia")
    assert [p.area for p in priv_ag.programas] == ["privada"]


@pytest.mark.asyncio
async def test_fetch_privada_lineas_es_tolerante_a_fallos():
    """Contrato: `fetch_privada_lineas` nunca lanza — ante cualquier error de red,
    auth o forma, devuelve []. Se apunta a un host inexistente para forzar el fallo."""
    from app.resumen_territorial import service as svc

    with patch.object(svc.settings, "gateway_base_url", "http://127.0.0.1:1"):
        resultado = await svc.fetch_privada_lineas()
    assert resultado == []


def test_map_privada_payload_reconoce_formas_plausibles_y_descarta_lo_raro():
    from app.resumen_territorial.service import _map_privada_payload

    data = {"localidades": [
        {"departamento": "Santa María", "localidad": "Alta Gracia", "por_estado": {"INGRESADO": 2, "FINALIZADA": 1}},
        {"nombre": "Sin depto", "total": 3},
        {"departamento": "X"},          # sin localidad → se descarta
        "basura",                        # no dict → se descarta
    ]}
    lineas = _map_privada_payload(data)
    assert len(lineas) == 2
    ag = next(l for l in lineas if l["nombre_localidad"] == "Alta Gracia")
    assert ag["programa"]["area"] == "privada"
    assert ag["programa"]["privada_conteos"]["total"] == 3
    assert _map_privada_payload("no reconocido") == []
