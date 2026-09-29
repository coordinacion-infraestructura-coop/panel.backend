"""Extracción de "Transferencias Automáticas a Municipios y Comunas"
(transparencia.cba.gov.ar) desde el PDF mensual publicado.

Productizado a partir del prototipo validado en la sesión 2026-09-29 contra
los PDF reales de julio 2026 (Municipios: 100% de validación; Comunas: 96%,
con una anomalía real de la fuente ya identificada, ver `validar_totales`).
No requiere red ni DB — es puro (bytes/path -> filas). Ver
docs/files/spec-resumen-territorial-tablero-v2.md §2.3 para el detalle de
cada hallazgo documentado acá.
"""
import re
import unicodedata
from pathlib import Path

import pdfplumber

CONCEPTOS = [
    "coparticipacion_ley_8663",
    "fasamu",
    "fofindes",
    "fondo_compensacion",
    "bono_consenso_fiscal",
    "total",
]
NUM_RE = re.compile(r"^[\d.]+$")
# pt: separa fragmentos de un mismo número (gap máx. observado ~17) de
# columnas reales (gap mín. observado ~35).
GAP_THRESHOLD = 25.0
# Una fila real siempre tiene 6 montos; texto de título/nota nunca llega a 6
# tokens numéricos — evita clasificar boilerplate con dígitos sueltos como dato.
MIN_NUM_TOKENS = 6
# Margen finito (no -inf) para la col. 1: algunas localidades tienen un número
# en el propio nombre (ej. "KILOMETRO 658") mucho más a la izquierda que
# cualquier desborde real de dígitos de un monto grande.
OUTER_MARGIN = 30.0


class ExtraccionError(Exception):
    """El PDF no tiene el layout esperado (columnas, headers) — no se puede
    extraer con confianza. Se propaga para que el caller decida (loguear
    como anomalía de la corrida, nunca inventar datos)."""


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_name(s: str) -> str:
    s = strip_accents(s).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def group_lines(words):
    lines = {}
    for w in words:
        key = round(w["top"], 0)
        lines.setdefault(key, []).append(w)
    return [sorted(lines[t], key=lambda w: w["x0"]) for t in sorted(lines.keys())]


def split_name_numeric(line_tokens):
    """Devuelve (texto_nombre, tokens_numericos) de una línea ya ordenada por x0."""
    i = 0
    while i < len(line_tokens) and not NUM_RE.match(line_tokens[i]["text"]):
        i += 1
    name = " ".join(t["text"] for t in line_tokens[:i])
    return name, line_tokens[i:]


def classify_line(name: str, full_text: str, num_token_count: int) -> str:
    """`name` es solo la porción de texto antes del primer monto (ver
    split_name_numeric). No alcanza con un prefijo "TOTAL GENERAL" sobre la
    línea completa: hay departamentos reales llamados "General Roca" y
    "General San Martín", así que "TOTAL General Roca" también empezaría con
    ese prefijo si se mirase la línea entera — de ahí el chequeo exacto."""
    name_up = name.upper().strip()
    if num_token_count < MIN_NUM_TOKENS:
        return "header_or_dept" if not any(ch.isdigit() for ch in full_text) else "boilerplate"
    if name_up == "TOTAL GENERAL":
        return "grand_total"
    if name_up.startswith("TOTAL "):
        return "dept_total"
    return "data"


def compute_column_bins(pdf_path: Path):
    """Deriva los 6 rangos [lo, hi) de las columnas numéricas a partir de la
    página 1. Las columnas están alineadas a la derecha: el x0 de un monto se
    corre a la izquierda cuanto más dígitos tiene (los TOTAL de departamento
    son los más anchos). Por eso los límites entre columnas se fijan en el
    punto medio del hueco real entre clusters, y los bordes externos quedan
    sin límite estricto — ver OUTER_MARGIN para la excepción de la col. 1."""
    numeric_x0 = []
    with pdfplumber.open(pdf_path) as pdf:
        words = pdf.pages[0].extract_words(x_tolerance=1, keep_blank_chars=False)
    for line in group_lines(words):
        name, num_tokens = split_name_numeric(line)
        full_text = " ".join(t["text"] for t in line)
        if classify_line(name, full_text, len(num_tokens)) != "data":
            continue
        numeric_x0.extend(t["x0"] for t in num_tokens)

    if not numeric_x0:
        raise ExtraccionError("No se encontró ninguna fila de datos en la página 1 del PDF.")

    numeric_x0.sort()
    clusters = []
    current = [numeric_x0[0]]
    for x in numeric_x0[1:]:
        if x - current[-1] > GAP_THRESHOLD:
            clusters.append(current)
            current = [x]
        else:
            current.append(x)
    clusters.append(current)

    if len(clusters) != 6:
        raise ExtraccionError(f"Se esperaban 6 columnas, se detectaron {len(clusters)}: {clusters}")

    bins = []
    for i, cluster in enumerate(clusters):
        lo = cluster[0] - OUTER_MARGIN if i == 0 else (clusters[i - 1][-1] + cluster[0]) / 2
        hi = float("inf") if i == len(clusters) - 1 else (cluster[-1] + clusters[i + 1][0]) / 2
        bins.append((lo, hi))
    return bins


def assign_to_bins(num_tokens, bins):
    """Reconstruye los 6 montos concatenando fragmentos que caen en el mismo
    bin. Tokens numéricos que quedan a la izquierda del primer bin (ej. un
    número que en realidad es parte del nombre, como "KILOMETRO 658") se
    devuelven aparte para que el llamador los reincorpore al nombre."""
    buckets = [[] for _ in bins]
    nombre_extra = []
    for t in num_tokens:
        if t["x0"] < bins[0][0]:
            nombre_extra.append(t)
            continue
        for i, (lo, hi) in enumerate(bins):
            if lo <= t["x0"] <= hi:
                buckets[i].append(t)
                break
        else:
            raise ExtraccionError(f"Token {t['text']!r} (x0={t['x0']}) no cae en ningún bin: {bins}")
    montos = []
    for bucket in buckets:
        bucket.sort(key=lambda t: t["x0"])
        raw = "".join(t["text"] for t in bucket)
        if not raw:
            raise ExtraccionError(f"Bin vacío al procesar tokens: {[t['text'] for t in num_tokens]}")
        montos.append(int(raw.replace(".", "")))
    nombre_extra.sort(key=lambda t: t["x0"])
    return montos, " ".join(t["text"] for t in nombre_extra)


def extract_pdf(pdf_path: Path, tipo: str, periodo: str) -> tuple[list[dict], dict, dict | None, list[tuple[str, str]]]:
    """Devuelve (filas_largas, totales_departamento, total_general, totales_duplicados)."""
    bins = compute_column_bins(pdf_path)
    filas: list[dict] = []
    totales_depto: dict[str, dict] = {}
    totales_depto_duplicados: list[tuple[str, str]] = []
    total_general: dict | None = None
    current_dept = None
    pending_dept_candidate = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1, keep_blank_chars=False)
            for line in group_lines(words):
                text = " ".join(t["text"] for t in line)
                name, num_tokens = split_name_numeric(line)
                kind = classify_line(name, text, len(num_tokens))

                if kind in ("header_or_dept", "boilerplate"):
                    if kind == "header_or_dept":
                        pending_dept_candidate = text.strip()
                    continue

                montos, nombre_extra = assign_to_bins(num_tokens, bins)
                if nombre_extra:
                    name = f"{name} {nombre_extra}".strip()

                if kind == "data":
                    if pending_dept_candidate is not None:
                        current_dept = pending_dept_candidate
                        pending_dept_candidate = None
                    for concepto, monto in zip(CONCEPTOS, montos):
                        filas.append({
                            "periodo": periodo,
                            "tipo": tipo,
                            "departamento_pdf": current_dept,
                            "nombre_pdf": name.strip(),
                            "concepto": concepto,
                            "monto": monto,
                        })
                elif kind == "dept_total":
                    depto_nombre = name.replace("TOTAL", "", 1).strip()
                    depto_key = normalize_name(depto_nombre)
                    if depto_key in totales_depto:
                        totales_depto_duplicados.append((depto_key, depto_nombre))
                    totales_depto[depto_key] = dict(zip(CONCEPTOS, montos))
                    pending_dept_candidate = None
                elif kind == "grand_total":
                    total_general = dict(zip(CONCEPTOS, montos))

    return filas, totales_depto, total_general, totales_depto_duplicados


def validar_totales(filas, totales_depto, total_general, tolerancia=50) -> list[str]:
    """Compara contra las filas TOTAL. Se tolera un pequeño desvío (redondeo
    de los coeficientes de coparticipación en la fuente: cada fila individual
    puede diferir en +/-1 peso del valor "exacto", y eso se acumula por
    departamento) — solo se reportan discrepancias mayores a `tolerancia`."""
    errores = []
    sums: dict[tuple[str, str], int] = {}
    for f in filas:
        key = (normalize_name(f["departamento_pdf"]), f["concepto"])
        sums[key] = sums.get(key, 0) + f["monto"]

    for depto_norm, esperado in totales_depto.items():
        for concepto, monto_esperado in esperado.items():
            calculado = sums.get((depto_norm, concepto))
            if calculado is None or abs(calculado - monto_esperado) > tolerancia:
                errores.append(
                    f"{depto_norm} / {concepto}: calculado={calculado} vs TOTAL={monto_esperado}"
                )

    if total_general:
        gran_sums = {c: 0 for c in CONCEPTOS}
        for esperado in totales_depto.values():
            for c, v in esperado.items():
                gran_sums[c] += v
        for c, v in total_general.items():
            if abs(gran_sums[c] - v) > tolerancia:
                errores.append(f"TOTAL GENERAL / {c}: suma deptos={gran_sums[c]} vs TOTAL GENERAL={v}")

    return errores
