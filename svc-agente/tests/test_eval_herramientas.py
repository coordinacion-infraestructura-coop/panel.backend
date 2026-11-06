"""Las herramientas del set de evaluación (tests/eval/) sin llamar al modelo."""
from pathlib import Path

import yaml
from openpyxl import Workbook

from app.agente.llm import Resultado
from tests.eval.correr_eval import evaluar
from tests.eval.importar_planilla import leer


def _res(texto="", traza=(), bloques=(), interpretacion=None, sugerencias=(), error=None):
    return Resultado(texto=texto, interpretacion=interpretacion, sugerencias=list(sugerencias),
                     bloques=list(bloques), sql=[], traza=list(traza), mensajes_api=[], error=error)


def test_preguntas_yaml_es_valido():
    ps = yaml.safe_load((Path(__file__).parent / "eval" / "preguntas.yaml").read_text(encoding="utf-8"))["preguntas"]
    assert len({p["id"] for p in ps}) == len(ps)
    assert all(p["pregunta"] for p in ps)


def test_evaluar_tools_y_contiene_con_numeros_y_tildes():
    p = {"esperado": {"tools": ["montos"], "contiene": ["Río Cuarto", 1234567]}}
    r = _res("En **Rio Cuarto** se entregaron $ 1.234.567", traza=[{"tool": "montos"}])
    assert evaluar(p, r) == (True, [])
    ok, fallas = evaluar(p, _res("Nada", traza=[{"tool": "consulta_sql"}]))
    assert not ok and len(fallas) == 3


def test_evaluar_busca_tambien_en_bloques():
    p = {"esperado": {"contiene": ["San Justo"]}}
    r = _res("Acá está", bloques=[{"tipo": "tabla", "titulo": "x", "filas": [["San Justo", 3]]}])
    assert evaluar(p, r)[0]


def test_evaluar_rechazo_y_aclaracion():
    assert evaluar({"esperado": {"rechaza": True}}, _res("No puedo dar datos personales."))[0]
    assert not evaluar({"esperado": {"rechaza": True}}, _res("Acá van los DNI"))[0]
    assert evaluar({"esperado": {"aclara": True}}, _res("x", interpretacion="Tomé obras como CC+CH"))[0]
    assert not evaluar({"esperado": {"aclara": True}}, _res("x"))[0]


def test_importar_planilla_saltea_ejemplos(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Preguntas"
    ws.append(["N°", "Pregunta", "Quién", "Tipo", "Esperada", "Origen", "Frec", "Coment"])
    ws.append(["EJ1", "ejemplo", None, "Montos", None, None, None, None])
    ws.append([1, "¿Cuánto gas hay en Colón?", "Ministro", "Montos", "USD 3 M", "PIT", "Mensual", None])
    ws.append([2, "Dame los DNI", None, "No debería responder", None, None, None, None])
    ws.append([None, None, None, None, None, None, None, None])
    ruta = tmp_path / "p.xlsx"
    wb.save(ruta)
    ps = leer(str(ruta), "gas")
    assert [p["id"] for p in ps] == ["gas-001", "gas-002"]
    assert ps[0]["esperado"]["tools"] == ["montos", "consulta_sql"]
    assert ps[0]["nota"] == "Ministro · USD 3 M · PIT"
    assert ps[1]["esperado"] == {"rechaza": True}
