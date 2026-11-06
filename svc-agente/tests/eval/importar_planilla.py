"""Convierte la planilla que completan las áreas (plantilla-preguntas-agente.xlsx, hoja
"Preguntas") en entradas de preguntas.yaml.

    python -m tests.eval.importar_planilla planilla.xlsx [--area vivienda] >> nuevas.yaml

Saltea las filas de ejemplo (N° que empieza con "EJ") y las vacías. La respuesta esperada que
escribió el área queda en `nota`: los valores de `esperado.contiene` se completan a mano
mirando el dato en db_agente, porque el texto libre ("12 convenios, $ 850 M") no se puede
comparar tal cual.
"""
import argparse
import sys

import yaml
from openpyxl import load_workbook

FAMILIAS = {
    "estado de programa": "estado_programa",
    "ficha de localidad o departamento": "ficha",
    "montos": "montos",
    "demoras / pendientes": "demoras",
    "toda la provincia / ranking": "provincia",
    "comparación": "comparacion",
    "no debería responder": "seguridad",
}
TOOLS = {
    "estado_programa": ["estado_programa_territorio", "consulta_sql"],
    "ficha": ["ficha_territorio"],
    "montos": ["montos", "consulta_sql"],
    "demoras": ["pendientes", "consulta_sql"],
}


def leer(ruta: str, area: str | None) -> list[dict]:
    hoja = load_workbook(ruta, read_only=True, data_only=True)["Preguntas"]
    out: list[dict] = []
    for fila in hoja.iter_rows(min_row=2, values_only=True):
        n, pregunta, quien, tipo, esperada, origen, _frec, coment = (list(fila) + [None] * 8)[:8]
        if not pregunta or str(n or "").upper().startswith("EJ"):
            continue
        familia = FAMILIAS.get(str(tipo or "").strip().lower(), "otra")
        esperado: dict = {}
        if familia in TOOLS:
            esperado["tools"] = TOOLS[familia]
        if familia == "seguridad":
            esperado["rechaza"] = True
        n_txt = str(n).strip() if n is not None else str(len(out) + 1)
        out.append({
            "id": f"{area or 'q'}-{n_txt.zfill(3)}",
            "familia": familia,
            "pregunta": str(pregunta).strip(),
            "esperado": esperado,
            "nota": " · ".join(str(x).strip() for x in (quien, esperada, origen, coment) if x),
        })
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("planilla")
    ap.add_argument("--area")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    yaml.safe_dump(leer(a.planilla, a.area), sys.stdout, allow_unicode=True, sort_keys=False, width=120)
