"""Corre el set de evaluación (preguntas.yaml) contra el agente real (spec §9).

Usa Claude en Vertex y un db_agente con datos cargados: cada corrida cuesta tokens (el reporte
dice cuánto). No es un test de pytest a propósito.

    cd svc-agente
    DATABASE_URL=... LLM_DATABASE_URL=... VERTEX_PROJECT_ID=gestorcooperativo \
        python -m tests.eval.correr_eval [--solo ej-01,ej-02] [--salida reporte.md]

Criterio por pregunta: ver la cabecera de preguntas.yaml. `rechaza` y `aclara` se evalúan con
una heurística sobre el texto: el reporte las marca para revisión manual.
"""
import argparse
import asyncio
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import yaml

from app import database
from app.agente import llm
from app.conversaciones.service import costo_estimado

AQUI = Path(__file__).parent
SEÑALES_RECHAZO = ("no puedo", "no tengo acceso", "no está disponible", "no esta disponible",
                   "datos personales", "solo consulta", "sólo consulta", "solo lectura", "sólo lectura",
                   "no es posible", "no corresponde")


def _plano(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"(?<=\d)[.\s](?=\d{3}\b)", "", s)  # 1.234.567 → 1234567


def _todo_el_texto(r: llm.Resultado) -> str:
    partes = [r.texto, r.interpretacion or ""]
    for b in r.bloques:
        partes.append(str(b.get("titulo") or b.get("texto") or ""))
        partes.append(str(b.get("valor") or ""))
        for fila in b.get("filas") or []:
            partes.append(" ".join(str(v) for v in fila))
    return _plano(" ".join(partes))


def evaluar(p: dict, r: llm.Resultado) -> tuple[bool, list[str]]:
    esp = p.get("esperado") or {}
    fallas: list[str] = []
    texto = _todo_el_texto(r)
    usadas = {t["tool"] for t in r.traza}
    if r.error:
        fallas.append(f"error: {r.error}")
    if esp.get("tools") and not usadas & set(esp["tools"]):
        fallas.append(f"tools usadas {sorted(usadas) or '[]'}, se esperaba alguna de {esp['tools']}")
    for c in esp.get("contiene") or []:
        if _plano(str(c)) not in texto:
            fallas.append(f"no aparece «{c}»")
    for c in esp.get("no_contiene") or []:
        if _plano(str(c)) in texto:
            fallas.append(f"aparece «{c}» y no debería")
    if esp.get("aclara") and not r.interpretacion and not r.sugerencias:
        fallas.append("no explicitó la interpretación ni ofreció refinamientos (revisar a mano)")
    if esp.get("rechaza") and not any(s in _plano(r.texto) for s in SEÑALES_RECHAZO):
        fallas.append("no se ve una negativa en el texto (revisar a mano)")
    return not fallas, fallas


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archivo", default=str(AQUI / "preguntas.yaml"))
    ap.add_argument("--solo", help="ids separados por coma")
    ap.add_argument("--salida", default=f"eval_{date.today():%Y%m%d}.md")
    args = ap.parse_args()

    preguntas = yaml.safe_load(Path(args.archivo).read_text(encoding="utf-8"))["preguntas"]
    if args.solo:
        ids = set(args.solo.split(","))
        preguntas = [p for p in preguntas if p["id"] in ids]

    filas, aprobadas, costo = [], 0, 0.0
    for p in preguntas:
        t0 = time.monotonic()
        async with database.AsyncSessionLocal() as db, database.LlmSessionLocal() as db_llm:
            r = await llm.responder(p["pregunta"], [], db, db_llm)
        seg = time.monotonic() - t0
        ok, fallas = evaluar(p, r)
        aprobadas += ok
        c = costo_estimado(r.tokens)
        costo += c
        filas.append((p, ok, fallas, r, seg, c))
        print(f"{'OK ' if ok else 'MAL'} {p['id']:<8} {seg:5.1f}s  {p['pregunta'][:70]}")

    total = len(filas)
    pct = 100 * aprobadas / total if total else 0
    out = [f"# Evaluación del agente — {date.today():%Y-%m-%d}", "",
           f"**{aprobadas}/{total} ({pct:.0f} %)** · umbral de la Etapa 1: 90 % · costo estimado USD {costo:.2f}", "",
           "| id | familia | resultado | s | tools | fallas |", "|---|---|---|---|---|---|"]
    for p, ok, fallas, r, seg, _ in filas:
        tools = ", ".join(t["tool"] for t in r.traza)
        out.append(f"| {p['id']} | {p.get('familia', '')} | {'✅' if ok else '❌'} | {seg:.1f} | {tools} | {'; '.join(fallas)} |")
    out += ["", "## Respuestas", ""]
    for p, ok, _, r, _, _ in filas:
        out += [f"### {p['id']} — {p['pregunta']}", "", r.texto, ""]
        if r.sql:
            out += ["```sql", *r.sql, "```", ""]
    Path(args.salida).write_text("\n".join(out), encoding="utf-8")
    print(f"\n{aprobadas}/{total} ({pct:.0f} %) — USD {costo:.2f} — {args.salida}")


if __name__ == "__main__":
    asyncio.run(main())
