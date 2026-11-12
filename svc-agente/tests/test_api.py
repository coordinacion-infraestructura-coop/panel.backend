import json

import pytest

from app.agente import llm
from tests.conftest import ADMIN, OPERADOR, AUTORIDAD
from tests.fake_llm import FakeLLM, tool


def _respuesta(t="Hay 2 convenios."):
    return ("tool_use", [tool("r", "responder", {"texto": t, "interpretacion": "i", "sugerencias": ["s1"], "bloques": []})])


@pytest.fixture
def guion():
    def _set(*respuestas):
        f = FakeLLM(list(respuestas))
        llm.set_cliente(f)
        return f
    yield _set
    llm.set_cliente(None)


async def _conv(client) -> str:
    r = await client.post("/api/v1/agente/conversaciones", json={})
    assert r.status_code == 201
    return r.json()["id"]


async def test_solo_admin_y_autoridad(client, as_user):
    as_user(OPERADOR)
    assert (await client.get("/api/v1/agente/conversaciones")).status_code == 403
    as_user(ADMIN)
    assert (await client.get("/api/v1/agente/conversaciones")).status_code == 200


async def test_sin_token_401(sesiones):
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/agente/conversaciones")).status_code == 401


async def test_pregunta_json_persiste_y_audita(client, cargado, guion):
    guion(_respuesta())
    cid = await _conv(client)
    r = await client.post(f"/api/v1/agente/conversaciones/{cid}/mensajes?stream=false", json={"texto": "¿Cómo está CC?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["texto"] == "Hay 2 convenios." and body["sugerencias"] == ["s1"]
    assert {f["fuente"] for f in body["fuentes"]} >= {"Vivienda"}

    d = (await client.get(f"/api/v1/agente/conversaciones/{cid}")).json()
    assert d["titulo"] == "¿Cómo está CC?"
    assert [m["rol"] for m in d["mensajes"]] == ["user", "assistant"]
    assert "api_json" not in d["mensajes"][1]

    from sqlalchemy import select
    from app.conversaciones.models import Interaccion
    i = (await cargado.execute(select(Interaccion))).scalar_one()
    assert i.email == AUTORIDAD.email and i.tokens["input_tokens"] == 100 and i.costo_estimado_usd > 0


async def test_segundo_turno_reenvia_historial(client, cargado, guion):
    f = guion(_respuesta("uno"), _respuesta("dos"))
    cid = await _conv(client)
    await client.post(f"/api/v1/agente/conversaciones/{cid}/mensajes?stream=false", json={"texto": "primera"})
    await client.post(f"/api/v1/agente/conversaciones/{cid}/mensajes?stream=false", json={"texto": "segunda"})
    roles = [m["role"] for m in f.llamadas[1]["messages"]]
    # turno 1 completo (user, assistant con tool_use, user con tool_result) + la nueva pregunta
    assert roles == ["user", "assistant", "user", "user"]


async def test_stream_sse(client, cargado, guion):
    guion(("tool_use", [tool("t", "resolver_territorio", {"texto": "San Justo"})]), _respuesta())
    cid = await _conv(client)
    r = await client.post(f"/api/v1/agente/conversaciones/{cid}/mensajes", json={"texto": "x"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    eventos = [b.split("\n") for b in r.text.strip().split("\n\n")]
    nombres = [e[0].removeprefix("event: ") for e in eventos]
    assert nombres == ["progreso", "progreso", "respuesta"]
    assert json.loads(eventos[-1][1].removeprefix("data: "))["texto"] == "Hay 2 convenios."
    d = (await client.get(f"/api/v1/agente/conversaciones/{cid}")).json()
    assert len(d["mensajes"]) == 2  # el stream también persiste


async def test_pregunta_repetida_no_vuelve_a_llamar_al_modelo(client, cargado, guion):
    f = guion(_respuesta("uno"))  # una sola respuesta guionada: una segunda llamada fallaría
    cid = await _conv(client)
    url = f"/api/v1/agente/conversaciones/{cid}/mensajes?stream=false"
    r1 = (await client.post(url, json={"texto": "¿Cómo está CC?"})).json()
    r2 = (await client.post(url, json={"texto": "  ¿cómo está  CC? "})).json()
    assert len(f.llamadas) == 1
    assert r2["mensaje_id"] == r1["mensaje_id"] and r2["texto"] == "uno"
    d = (await client.get(f"/api/v1/agente/conversaciones/{cid}")).json()
    assert len(d["mensajes"]) == 2  # no se duplica en el historial ni en la auditoría


async def test_stream_escapa_separadores_de_linea_unicode(client, cargado, guion):
    ls, ps = chr(0x2028), chr(0x2029)  # separadores de línea/párrafo Unicode
    guion(_respuesta(f"antes{ls}después{ps}fin"))
    cid = await _conv(client)
    r = await client.post(f"/api/v1/agente/conversaciones/{cid}/mensajes", json={"texto": "x"})
    assert ls not in r.text and ps not in r.text
    data = r.text.strip().split("\n\n")[-1].split("\n")[1].removeprefix("data: ")
    assert json.loads(data)["texto"] == f"antes{ls}después{ps}fin"


async def test_conversacion_ajena_404(client, as_user, cargado, guion):
    cid = await _conv(client)
    as_user(ADMIN)
    assert (await client.get(f"/api/v1/agente/conversaciones/{cid}")).status_code == 404
    assert (await client.post(f"/api/v1/agente/conversaciones/{cid}/mensajes?stream=false", json={"texto": "x"})).status_code == 404
    assert (await client.delete(f"/api/v1/agente/conversaciones/{cid}")).status_code == 404


async def test_borrar_y_paginar(client):
    ids = [await _conv(client) for _ in range(3)]
    assert (await client.delete(f"/api/v1/agente/conversaciones/{ids[0]}")).status_code == 204
    r = (await client.get("/api/v1/agente/conversaciones?limit=1")).json()
    assert r["total"] == 2 and len(r["items"]) == 1


async def test_cuota_diaria(client, cargado, guion, monkeypatch):
    from app.conversaciones import service
    monkeypatch.setattr(service.settings, "cuota_diaria", 1)
    guion(_respuesta())
    cid = await _conv(client)
    url = f"/api/v1/agente/conversaciones/{cid}/mensajes?stream=false"
    assert (await client.post(url, json={"texto": "a"})).status_code == 200
    r = await client.post(url, json={"texto": "b"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "CUOTA_DIARIA_AGOTADA"


async def test_feedback(client, as_user, cargado, guion):
    guion(_respuesta())
    cid = await _conv(client)
    mid = (await client.post(f"/api/v1/agente/conversaciones/{cid}/mensajes?stream=false", json={"texto": "a"})).json()["mensaje_id"]
    assert (await client.post(f"/api/v1/agente/mensajes/{mid}/feedback", json={"valor": -1, "comentario": "mal"})).status_code == 204
    assert (await client.post(f"/api/v1/agente/mensajes/{mid}/feedback", json={"valor": 1})).status_code == 204
    assert (await client.post(f"/api/v1/agente/mensajes/{mid}/feedback", json={"valor": 5})).status_code == 422
    as_user(ADMIN)
    assert (await client.post(f"/api/v1/agente/mensajes/{mid}/feedback", json={"valor": 1})).status_code == 404


async def test_refrescar_interno_y_estado(client, monkeypatch):
    from app.etl import carga
    from tests.conftest import lector_de, raw_fuentes
    monkeypatch.setattr(carga, "leer_fuente_postgres", lector_de(raw_fuentes(), fallan={"privada"}))
    import app.internal.router as ir

    async def _ref(db):
        return await carga.refrescar(db, carga.leer_fuente_postgres)
    monkeypatch.setattr(ir, "refrescar", _ref)
    r = await client.post("/internal/agente/refrescar")
    assert r.status_code == 200 and r.json()["fuentes"]["privada"]["estado"] == "error"
    e = (await client.get("/api/v1/agente/estado")).json()
    assert {f["fuente"]: f["estado"] for f in e["fuentes"]}["Vivienda"] == "ok"
