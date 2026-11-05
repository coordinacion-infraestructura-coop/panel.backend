import json

import pytest

from app.agente import llm
from tests.fake_llm import FakeLLM, texto, tool


@pytest.fixture
def fake():
    def _set(guion):
        f = FakeLLM(guion)
        llm.set_cliente(f)
        return f
    yield _set
    llm.set_cliente(None)


async def test_flujo_tools_y_responder(cargado, db_llm, fake):
    f = fake([
        ("tool_use", [tool("t1", "resolver_territorio", {"texto": "San Justo"})]),
        ("tool_use", [tool("t2", "estado_programa_territorio", {"programa": "cc", "departamento": "San Justo", "id_geo": None})]),
        ("tool_use", [texto("Listo."), tool("t3", "responder", {
            "texto": "En San Justo hay 2 convenios de Cordón Cuneta.", "interpretacion": "Cordón Cuneta, depto San Justo",
            "sugerencias": ["¿Y Córdoba Hogar?", "¿Cuáles están trabados?", "¿Y en Unión?", "sobra"], "bloques": ["b1", "b99"]})]),
    ])
    progreso = []

    async def prog(t):
        progreso.append(t)

    r = await llm.responder("¿Cómo está CC en San Justo?", [], cargado, db_llm, progreso=prog)
    assert r.error is None
    assert r.texto.startswith("En San Justo")
    assert len(r.sugerencias) == 3
    assert [b["id"] for b in r.bloques] == ["b1"]  # ids inexistentes se ignoran
    assert progreso == ["resolver_territorio", "estado_programa_territorio"]
    assert [t["tool"] for t in r.traza] == ["resolver_territorio", "estado_programa_territorio"]
    # el resultado de la tool le llega al modelo con referencias a bloques, no con las tablas
    resultado = json.loads(f.llamadas[2]["messages"][-1]["content"][0]["content"])
    assert resultado["bloques"][0]["id"] == "b1" and "filas" not in resultado["bloques"][0]
    # historial append-only: termina con el tool_result de `responder`
    assert r.mensajes_api[-1]["role"] == "user"
    assert r.mensajes_api[-1]["content"][0]["tool_use_id"] == "t3"
    assert r.tokens["input_tokens"] == 300
    # system prompt cacheable y estable
    assert f.llamadas[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert f.llamadas[0]["system"] == f.llamadas[2]["system"]


async def test_consulta_sql_rechazada_vuelve_al_modelo(cargado, db_llm, fake):
    f = fake([
        ("tool_use", [tool("t1", "consulta_sql", {"sql": "DELETE FROM ag_gestiones", "motivo": "x"})]),
        ("tool_use", [tool("t2", "consulta_sql", {"sql": "SELECT localidad, poblacion FROM ag_localidades WHERE poblacion > 1000 ORDER BY poblacion DESC", "motivo": "x"})]),
        ("end_turn", [texto("Villa María es la más poblada.")]),
    ])
    r = await llm.responder("¿Qué localidad es la más poblada?", [], cargado, db_llm)
    primer = f.llamadas[1]["messages"][-1]["content"][0]
    assert primer["is_error"] is True and "rechazada" in primer["content"]
    # renderizado en el dialecto de la sesión (en tests SQLite agrega NULLS FIRST para
    # conservar la semántica de Postgres)
    assert len(r.sql) == 1 and "FROM ag.ag_localidades" in r.sql[0] and r.sql[0].endswith("LIMIT 500")
    # sin `responder`: texto libre + todos los bloques generados
    assert r.texto == "Villa María es la más poblada."
    assert r.bloques[0]["filas"][0] == ["Villa María", 90000]
    assert r.filas_devueltas == 2


async def test_consulta_sql_no_puede_borrar_datos(cargado, db_llm, fake):
    """Aunque el validador se saltee, la sesión LLM hace rollback: nada persiste."""
    from sqlalchemy import func, select, text
    from app.semantica.models import AgGestion
    from app.agente.herramientas import Turno, ejecutar_sql
    import app.agente.herramientas as h
    from app.agente.sql_guard import SqlValidado

    orig = h.validar
    h.validar = lambda sql, **k: SqlValidado(sql="DELETE FROM ag.ag_gestiones", limite_aplicado=1)
    try:
        await ejecutar_sql(db_llm, "x", Turno())
    finally:
        h.validar = orig
    assert (await cargado.execute(select(func.count()).select_from(AgGestion))).scalar_one() == 3


async def test_maximo_de_rondas(cargado, db_llm, fake, monkeypatch):
    monkeypatch.setattr(llm.settings, "max_rondas_tools", 2)
    f = fake([
        ("tool_use", [tool("t1", "resolver_territorio", {"texto": "x"})]),
        ("tool_use", [tool("t2", "resolver_territorio", {"texto": "y"})]),
        ("tool_use", [tool("t3", "responder", {"texto": "Corto.", "interpretacion": "-", "sugerencias": [], "bloques": []})]),
    ])
    r = await llm.responder("?", [], cargado, db_llm)
    assert r.texto == "Corto."
    assert "máximo" in f.llamadas[2]["messages"][-1]["content"][0]["text"]


async def test_error_del_modelo_deja_historial_valido(cargado, db_llm):
    class Roto:
        async def crear(self, **k):
            raise RuntimeError("vertex caído")

    llm.set_cliente(Roto())
    try:
        r = await llm.responder("hola", [], cargado, db_llm)
    finally:
        llm.set_cliente(None)
    assert r.error and "vertex caído" in r.error
    assert [m["role"] for m in r.mensajes_api] == ["user", "assistant"]
    assert "Probá de nuevo" in r.texto


async def test_refusal(cargado, db_llm, fake):
    fake([("refusal", [])])
    r = await llm.responder("algo", [], cargado, db_llm)
    assert "No puedo responder" in r.texto
