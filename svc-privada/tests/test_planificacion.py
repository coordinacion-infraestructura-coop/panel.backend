"""Planificación de programas por localidad — Fase 1 (spec-privada-planificacion-programas.md)."""
import pytest

from app.auth import AuthUser
from app.territorial.models import GeoLocalidad, LocalidadInfo
from tests.conftest import CONSULTA_USER, OPERADOR_USER

BASE = "/api/v1/privada/planificacion"
SUPERVISOR = AuthUser(uid="sup", email="sup@test.com", role="Supervisor", secretarias=["privada"])
AUTORIDAD = AuthUser(uid="aut", email="aut@test.com", role="Autoridad", secretarias=["privada"])
OPERADOR_VIVIENDA = AuthUser(uid="ov", email="ov@test.com", role="Operador", secretarias=["vivienda"])


@pytest.fixture
async def padron(db_session):
    db_session.add_all([
        GeoLocalidad(id_geo="1", departamento="CALAMUCHITA", localidad="EMBALSE", activo=True),
        GeoLocalidad(id_geo="2", departamento="CALAMUCHITA", localidad="CALMAYO", activo=True),
        GeoLocalidad(id_geo="22", departamento="COLÓN", localidad="AGUA DE ORO", activo=True),
        GeoLocalidad(id_geo="99", departamento="COLÓN", localidad="BAJA", activo=False),
        LocalidadInfo(departamento="CALAMUCHITA", localidad="EMBALSE", id_geo="1", habitantes=9681,
                      tipo_localidad="Municipio", color_semaforo="VERDE"),
    ])
    await db_session.flush()


async def _programa(client, nombre="Cordón Cuneta", fuente="cordon_cuneta"):
    r = await client.post(f"{BASE}/programas", json={"nombre": nombre, "area": "vivienda", "fuente": fuente})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _prio(client, pid, codigo):
    prios = (await client.get(f"{BASE}/programas/{pid}/prioridades")).json()
    return next(p["id"] for p in prios if p["codigo"] == codigo)


async def test_programa_nuevo_trae_prioridades_y_columnas_por_defecto(client, padron):
    pid = await _programa(client)
    prios = (await client.get(f"{BASE}/programas/{pid}/prioridades")).json()
    assert [p["codigo"] for p in prios] == ["1", "2", "3", "4", "5", "X"]
    assert next(p for p in prios if p["codigo"] == "X")["excluye"] is True
    cols = (await client.get(f"{BASE}/programas/{pid}/columnas")).json()
    assert [c["clave"] for c in cols] == ["anuncio_gobernador", "monto_sugerido", "monto_firmado", "observacion"]
    estados = (await client.get(f"{BASE}/programas/{pid}/estados")).json()
    assert [(e["nombre"], e["color_bg"]) for e in estados] == [("Resuelto por ATP", "#D1C4E9")]


async def test_nombre_duplicado_409(client, padron):
    await _programa(client)
    r = await client.post(f"{BASE}/programas", json={"nombre": "cordon cuneta ", "area": "vivienda"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOMBRE_DUPLICADO"


async def test_listado_padron_activo_ordenado_por_prioridad(client, padron):
    pid = await _programa(client)
    p1, px = await _prio(client, pid, "1"), await _prio(client, pid, "X")
    await client.patch(f"{BASE}/programas/{pid}/localidades/22", json={"updated_at": None, "prioridad_id": px})
    await client.patch(f"{BASE}/programas/{pid}/localidades/2", json={"updated_at": None, "prioridad_id": p1})
    body = (await client.get(f"{BASE}/programas/{pid}/localidades")).json()
    assert body["total"] == 3  # la inactiva no aparece
    assert [i["id_geo"] for i in body["items"]] == ["2", "22", "1"]  # 1 → X (excluye) → sin clasificar
    embalse = body["items"][2]
    assert embalse["habitantes"] == 9681 and embalse["semaforo"] == "VERDE" and embalse["valores"] == {}
    solo_colon = (await client.get(f"{BASE}/programas/{pid}/localidades", params={"departamento": "colón"})).json()
    assert [i["id_geo"] for i in solo_colon["items"]] == ["22"]


async def test_upsert_historial_y_lock_optimista(client, padron):
    pid = await _programa(client)
    p2 = await _prio(client, pid, "2")
    estado = (await client.post(f"{BASE}/programas/{pid}/estados", json={"nombre": "Espera doc. técnica"})).json()

    r = await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={
        "updated_at": None, "prioridad_id": p2, "estado_id": estado["id"], "ok_gobernador": True,
        "valores": {"monto_sugerido": 200000000, "observacion": "EN OBRA"},
    })
    assert r.status_code == 200, r.text
    fila = r.json()
    assert fila["valores"] == {"monto_sugerido": 200000000, "observacion": "EN OBRA"} and fila["cambios"] == 5

    # el cliente que todavía no vio la fila (updated_at null) pierde
    r = await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={"updated_at": None, "ok_gobernador": False})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "CONFLICTO_EDICION"

    r = await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={
        "updated_at": fila["updated_at"], "valores": {"observacion": None},
    })
    assert r.status_code == 200 and r.json()["valores"] == {"monto_sugerido": 200000000}

    hist = (await client.get(f"{BASE}/programas/{pid}/localidades/1/historial")).json()
    assert hist[0]["campo"] == "observacion" and hist[0]["valor_anterior"] == "EN OBRA" and hist[0]["valor_nuevo"] is None
    legibles = {h["campo"]: h["valor_nuevo"] for h in hist[1:]}
    assert legibles["prioridad"] == "Prioridad 2"
    assert legibles["estado"] == "Espera doc. técnica"
    assert legibles["ok_gobernador"] == "Sí"


async def test_sin_cambios_no_escribe_historial(client, padron):
    pid = await _programa(client)
    r = await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={"updated_at": None, "valores": {"observacion": ""}})
    assert r.status_code == 200 and r.json()["cambios"] == 0 and r.json()["updated_at"] is None


async def test_validaciones_de_valores(client, padron):
    pid = await _programa(client)
    otro = await _programa(client, "Córdoba Hogar", "cordoba_hogar")
    prio_otro = await _prio(client, otro, "1")
    casos = [
        ({"prioridad_id": prio_otro}, "CATALOGO_DE_OTRO_PROGRAMA"),
        ({"valores": {"no_existe": 1}}, "COLUMNA_DESCONOCIDA"),
        ({"valores": {"monto_sugerido": -5}}, "VALOR_INVALIDO"),
        ({"valores": {"monto_sugerido": "200M"}}, "VALOR_INVALIDO"),
        ({"valores": {"anuncio_gobernador": "SI"}}, "VALOR_INVALIDO"),
    ]
    for body, code in casos:
        r = await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={"updated_at": None, **body})
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, body
    r = await client.patch(f"{BASE}/programas/{pid}/localidades/99", json={"updated_at": None, "ok_gobernador": True})
    assert r.status_code == 404


async def test_columnas_agregadas_lista_fecha_y_cambio_de_tipo(client, padron):
    pid = await _programa(client)
    r = await client.post(f"{BASE}/programas/{pid}/columnas", json={"nombre": "Tipo de obra", "tipo": "lista"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "OPCIONES_REQUERIDAS"
    lista = (await client.post(f"{BASE}/programas/{pid}/columnas", json={
        "nombre": "Tipo de obra", "tipo": "lista", "opciones": ["Cordón", "Media caña"],
    })).json()
    fecha = (await client.post(f"{BASE}/programas/{pid}/columnas", json={"nombre": "Fecha audiencia", "tipo": "fecha"})).json()
    repetida = (await client.post(f"{BASE}/programas/{pid}/columnas", json={"nombre": "tipo de OBRA", "tipo": "texto"}))
    assert repetida.status_code == 409  # mismo nombre normalizado
    assert lista["clave"] == "tipo_de_obra" and fecha["clave"] == "fecha_audiencia"

    r = await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={
        "updated_at": None, "valores": {"tipo_de_obra": "Media caña", "fecha_audiencia": "2026-11-24"},
    })
    assert r.status_code == 200, r.text
    r2 = await client.patch(f"{BASE}/programas/{pid}/localidades/2", json={"updated_at": None, "valores": {"tipo_de_obra": "Otra"}})
    assert r2.status_code == 422

    # cambiar el tipo de una columna con datos → 409; renombrar sí
    r = await client.patch(f"{BASE}/programas/{pid}/columnas/{fecha['id']}", json={"tipo": "texto"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "COLUMNA_CON_DATOS"
    r = await client.patch(f"{BASE}/programas/{pid}/columnas/{fecha['id']}", json={"nombre": "Audiencia"})
    assert r.status_code == 200 and r.json()["clave"] == "fecha_audiencia"


async def test_prioridad_borrada_sigue_en_la_fila(client, padron):
    pid = await _programa(client)
    p5 = await _prio(client, pid, "5")
    await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={"updated_at": None, "prioridad_id": p5})
    assert (await client.delete(f"{BASE}/programas/{pid}/prioridades/{p5}")).status_code == 200
    items = (await client.get(f"{BASE}/programas/{pid}/localidades")).json()["items"]
    assert next(i for i in items if i["id_geo"] == "1")["prioridad_id"] == p5
    vivas = (await client.get(f"{BASE}/programas/{pid}/prioridades")).json()
    todas = (await client.get(f"{BASE}/programas/{pid}/prioridades", params={"incluir_eliminados": "true"})).json()
    assert p5 not in [p["id"] for p in vivas]
    assert next(p for p in todas if p["id"] == p5)["eliminado"] is True
    # y ya no se puede asignar a otra localidad
    r = await client.patch(f"{BASE}/programas/{pid}/localidades/2", json={"updated_at": None, "prioridad_id": p5})
    assert r.status_code == 422


async def test_permisos(client, padron, as_user):
    pid = await _programa(client)
    # Autoridad y usuarios sin Privada: afuera, también para leer
    for u in (AUTORIDAD, OPERADOR_VIVIENDA):
        as_user(u)
        assert (await client.get(f"{BASE}/programas")).status_code == 403
    # Consulta: lee, no escribe
    as_user(CONSULTA_USER)
    assert (await client.get(f"{BASE}/programas/{pid}/localidades")).status_code == 200
    assert (await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={"updated_at": None, "ok_gobernador": True})).status_code == 403
    # Operador: edita valores, no configura
    as_user(OPERADOR_USER)
    assert (await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={"updated_at": None, "ok_gobernador": True})).status_code == 200
    assert (await client.post(f"{BASE}/programas/{pid}/estados", json={"nombre": "x"})).status_code == 403
    assert (await client.post(f"{BASE}/programas", json={"nombre": "Otro", "area": "otra"})).status_code == 403
    # Supervisor: configura, no borra programas
    as_user(SUPERVISOR)
    assert (await client.post(f"{BASE}/programas/{pid}/estados", json={"nombre": "Notificado"})).status_code == 201
    assert (await client.delete(f"{BASE}/programas/{pid}")).status_code == 403


async def test_borrar_programa_soft(client, padron):
    pid = await _programa(client)
    assert (await client.delete(f"{BASE}/programas/{pid}")).status_code == 200
    assert (await client.get(f"{BASE}/programas/{pid}/localidades")).status_code == 404
    assert (await client.get(f"{BASE}/programas")).json() == []
    # el nombre queda libre
    assert (await client.post(f"{BASE}/programas", json={"nombre": "Cordón Cuneta", "area": "vivienda"})).status_code == 201


# --- Fases 2–3: cruces con otros servicios (mockeados) ------------------------------------

from unittest.mock import AsyncMock, patch  # noqa: E402

from app.integrations import planificacion_fuentes as fx  # noqa: E402

LINEAS_CH = {
    "1": [{"id_geo": "1", "estado_general": {"label": "Convenio Firmado", "bg": "#E0F7FA", "text_color": "#006064"},
           "ok_gob": True, "convenio_firmado": True, "fecha_firma_convenio": "2026-06-23", "monto": 1.0}],
}
EXTERNOS = (
    {"1": {"id_geo": "1", "visita_gobernador": {"visitada": True, "fecha_ultima": "2026-09-20"},
           "coparticipacion_anual": {"monto": 300.0, "meses": 12}}},
    {"desde": "2025-08-01", "hasta": "2026-07-01", "meses_ventana": 12},
)


async def test_cruces_con_panel_y_datos_externos(client, padron):
    pid = await _programa(client, "Córdoba Hogar", "cordoba_hogar")
    with patch.object(fx, "lineas_del_panel", new=AsyncMock(return_value=(LINEAS_CH, 2))), \
         patch.object(fx, "datos_externos", new=AsyncMock(return_value=EXTERNOS)):
        body = (await client.get(f"{BASE}/programas/{pid}/localidades")).json()
    assert body["fuentes"] == {"panel": "ok", "panel_sin_id_geo": "2", "datos_externos": "ok"}
    por = {i["id_geo"]: i for i in body["items"]}
    assert por["1"]["en_panel"]["estado"] == "si" and por["1"]["en_panel"]["lineas"][0]["estado_general"]["label"] == "Convenio Firmado"
    assert por["1"]["convenio"] == {"firmado": True, "fecha": "2026-06-23"}
    assert por["1"]["ok_gobernador_panel"] is True
    assert por["1"]["visita_gobernador"] == {"visitada": True, "fecha_ultima": "2026-09-20"}
    assert por["1"]["coparticipacion_anual"]["monto"] == 300.0 and por["1"]["coparticipacion_anual"]["hasta"] == "2026-07-01"
    assert por["2"]["en_panel"]["estado"] == "no" and por["2"]["convenio"] == {"firmado": False, "fecha": None}
    assert por["2"]["visita_gobernador"] is None  # no está en la planilla de visitas: sin dato, no "No"


async def test_cc_no_informa_convenio(client, padron):
    pid = await _programa(client)
    with patch.object(fx, "lineas_del_panel", new=AsyncMock(return_value=({"1": [{"ok_gob": False}]}, 0))), \
         patch.object(fx, "datos_externos", new=AsyncMock(return_value=({}, None))):
        por = {i["id_geo"]: i for i in (await client.get(f"{BASE}/programas/{pid}/localidades")).json()["items"]}
    assert por["1"]["convenio"] is None and por["1"]["ok_gobernador_panel"] is False


async def test_fuentes_caidas_quedan_sin_dato(client, padron):
    pid = await _programa(client)
    caida = AsyncMock(side_effect=fx.FuenteNoDisponible("caído"))
    with patch.object(fx, "lineas_del_panel", new=caida), patch.object(fx, "datos_externos", new=caida):
        body = (await client.get(f"{BASE}/programas/{pid}/localidades")).json()
    assert body["fuentes"] == {"panel": "sin_dato", "datos_externos": "sin_dato"}
    assert all(i["en_panel"]["estado"] == "sin_dato" for i in body["items"])  # nunca "no"
    # la planilla sigue editable
    r = await client.patch(f"{BASE}/programas/{pid}/localidades/1", json={"updated_at": None, "ok_gobernador": True})
    assert r.status_code == 200


async def test_programa_sin_fuente_no_consulta_panel(client, padron):
    pid = await _programa(client, "Plan propio", None)
    panel = AsyncMock()
    with patch.object(fx, "lineas_del_panel", new=panel), \
         patch.object(fx, "datos_externos", new=AsyncMock(return_value=({}, None))):
        body = (await client.get(f"{BASE}/programas/{pid}/localidades")).json()
    panel.assert_not_called()
    assert body["fuentes"] == {"datos_externos": "ok"} and body["items"][0]["en_panel"] is None


async def test_fetch_apagado_por_defecto():
    fx.limpiar_cache()
    with pytest.raises(fx.FuenteNoDisponible):
        await fx.lineas_del_panel("cordon_cuneta")


async def test_rollups_gas_y_atp_se_normalizan(monkeypatch):
    fx.limpiar_cache()
    async def fake_get(base, path, params=None):
        if "gasifera" in path:
            return [{"id_geo": "5", "en_curso": 0, "monto_solicitado_sum": 10.0}, {"id_geo": None}]
        return [{"id_geo": "6", "monto_total_sum": 100.0, "entregado_sum": 40.0}]
    monkeypatch.setattr(fx, "_get", fake_get)
    gas, sin = await fx.lineas_del_panel("gas_pit")
    assert gas["5"][0]["estado_general"]["label"] == "Cumplido" and sin == 1
    atp, _ = await fx.lineas_del_panel("atp")
    assert atp["6"][0]["estado_general"]["label"] == "Parcial"
