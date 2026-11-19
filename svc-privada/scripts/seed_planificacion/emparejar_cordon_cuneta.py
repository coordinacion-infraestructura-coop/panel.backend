"""Empareja la pestaña GENERAL de 'Cordón Cuneta OK.xlsx' contra el padrón
viv_geo_localidades reconstruido desde el repo (docs/data/geo_localidades.json
+ migraciones 0033/0042) y los alias de viv_geo_alias_manual (seed_data.py +
0036). Replica app/geo/matching.py. Uso:
    python -I match_cc.py <xlsx> <repo_root> <out_dir>
"""
import csv, json, re, sys, unicodedata, difflib, collections
from pathlib import Path

import openpyxl

XLSX, REPO, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])


# ── réplica de app/geo/matching.py ───────────────────────────────────────────
def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def normalize_name(s):
    return strip_accents(s).strip().lower() if s else ""

def normalize_departamento(s):
    n = normalize_name(s)
    n = re.sub(r"\bgeneral\b", "gral", n)
    n = re.sub(r"\bpresidente\b", "pte", n)
    return n

def candidatos_localidad(nombre):
    if not nombre:
        return set()
    keys = {normalize_name(nombre)}
    keys.add(normalize_name(re.split(r"\(", nombre)[0]))
    m = re.search(r"\(([^)]*)\)", nombre)
    if m:
        keys.add(normalize_name(m.group(1)))
        keys.add(re.sub(r"^(est\.?|estaci[oó]n)\s+", "", normalize_name(m.group(1))))
    for parte in nombre.split(" - "):
        keys.add(normalize_name(parte))
    return {k for k in keys if k}


# ── normalizaciones extra (solo para este script) ────────────────────────────
def dep_key(s):
    n = normalize_departamento(s).replace(".", " ")
    n = re.sub(r"^pte\s+", "", n)
    return re.sub(r"\s+", " ", n).strip()

ABREV = [
    (r"\bva\b\.?", "villa"), (r"\bv\b\.?", "villa"), (r"\bsta\b\.?", "santa"),
    (r"\bgral\b\.?", "general"), (r"\best\b\.?", "estacion"), (r"\bcol\b\.?", "colonia"),
    (r"\barg\b\.?", "argentinas"), (r"\bcap\b\.?", "capitan"), (r"\bpque\b\.?", "parque"),
    (r"\b4\b", "cuatro"),
]

def compact(s):
    """normalize_name + sin puntuación + espacios colapsados."""
    n = normalize_name(s)
    n = re.sub(r"[^a-z0-9ñ ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()

def expand(s):
    n = normalize_name(s).replace(".", ". ")
    for pat, rep in ABREV:
        n = re.sub(pat, rep, n)
    return compact(n)


# ── padrón ───────────────────────────────────────────────────────────────────
padron = json.load(open(REPO / "docs/data/geo_localidades.json", encoding="utf-8"))
INACTIVOS_0033 = {"555", "43", "81", "285", "78", "213", "212"}
for g in padron:
    g["activo"] = g["id_geo"] not in INACTIVOS_0033
    g["localidad"] = g["localidad"].upper()  # 0035
# 0042: altas con id_geo asignado en runtime (max+1). No se usan como match firme.
ALTAS_0042 = [("SANTIAGO TEMPLE", "RÍO SEGUNDO"), ("KILÓMETRO 658", "RÍO PRIMERO")]
max_id = max(int(g["id_geo"]) for g in padron)
ALTAS_PROBABLES = {normalize_name(l): (str(max_id + 1 + i), d, l) for i, (l, d) in enumerate(ALTAS_0042)}

activos = [g for g in padron if g["activo"]]
por_id = {g["id_geo"]: g for g in padron}
# índice por depto → {clave: [filas]}
idx_exact = collections.defaultdict(lambda: collections.defaultdict(list))
idx_comp = collections.defaultdict(lambda: collections.defaultdict(list))
for g in activos:
    dk = dep_key(g["departamento"])
    for k in candidatos_localidad(g["localidad"]):
        idx_exact[dk][k].append(g)
        idx_comp[dk][compact(k)].append(g)
        idx_comp[dk][expand(k)].append(g)
deps_padron = set(idx_exact)

# ── alias (seed_data.py + 0036) ──────────────────────────────────────────────
sys.path.insert(0, str(REPO / "services/svc-vivienda"))
from app.geo import seed_data  # noqa: E402  (solo listas de tuplas)
alias_raw = []
for name in dir(seed_data):
    if name.startswith("_ALIAS_RAW"):
        alias_raw += getattr(seed_data, name)
alias_raw += [("Barrio Chingolo", None, "0036", "mi_lugar"), ("Santa Teresa", None, "0036", "mi_lugar"),
              ("Paraje El Barrial", None, "0036", "privada")]
ALIAS = {}
for texto, id_geo, motivo, origen in alias_raw:
    ALIAS[normalize_name(texto)] = (id_geo, texto, motivo)
    ALIAS.setdefault(compact(texto), (id_geo, texto, motivo))
    ALIAS.setdefault(expand(texto), (id_geo, texto, motivo))


def uniq(filas):
    d = {f["id_geo"]: f for f in filas}
    return list(d.values())


def resolver(dep, loc):
    dk = dep_key(dep)
    if dk not in deps_padron:
        return dict(metodo="sin_match", nota=f"departamento '{dep}' no está en el padrón")
    loc_clean = loc.strip().rstrip(")").strip() if loc.count(")") > loc.count("(") else loc.strip()
    nota_clean = "paréntesis sobrante" if loc_clean != loc.strip() else ""
    # 1. exacto normalizado (réplica del resolver: candidatos del lado fuente y padrón)
    for k, extra in [(normalize_name(loc_clean), "")] + [(k, "alias de la fuente") for k in candidatos_localidad(loc_clean) | {normalize_name(p) for p in loc_clean.split("-") if p.strip()}]:
        filas = uniq(idx_exact[dk].get(k, []))
        if len(filas) == 1:
            return dict(metodo="exacto", geo=filas[0], score=100, nota="; ".join(x for x in [nota_clean, extra and f"candidato '{k}'"] if x))
    # 1b. exacto tras quitar puntuación / expandir abreviaturas
    for k, why in [(compact(loc_clean), "sin puntuación"), (expand(loc_clean), "abreviaturas expandidas")]:
        filas = uniq(idx_comp[dk].get(k, []))
        if len(filas) == 1:
            return dict(metodo="exacto", geo=filas[0], score=100, nota="; ".join(x for x in [nota_clean, why] if x))
    # 2. alias manual
    for k in (normalize_name(loc_clean), compact(loc_clean), expand(loc_clean)):
        if k in ALIAS:
            id_geo, texto, motivo = ALIAS[k]
            if id_geo is None:
                alta = ALTAS_PROBABLES.get(normalize_name(texto))
                if alta and dep_key(alta[1]) == dk:
                    return dict(metodo="revisar", score=None,
                                nota=f"alias '{texto}' repuntado por migración 0042 a una alta del padrón "
                                     f"('{alta[2]}', {alta[1]}); id_geo asignado en runtime, probable {alta[0]}",
                                cands=[f"{alta[0]}? {alta[2]} ({alta[1]}, alta 0042)"])
                return dict(metodo="sin_match", nota=f"alias '{texto}' confirmado sin vínculo")
            g = por_id[id_geo]
            if dep_key(g["departamento"]) != dk:
                return dict(metodo="revisar", geo=None, nota=f"alias '{texto}' apunta a otro departamento ({g['departamento']})",
                            cands=[f"{id_geo} {g['localidad']} ({g['departamento']})"])
            return dict(metodo="alias", geo=g, score=100, nota=f"alias '{texto}': {motivo}")
    # 2b. alta 0042 sin alias previo
    alta = ALTAS_PROBABLES.get(normalize_name(loc_clean))
    if alta and dep_key(alta[1]) == dk:
        return dict(metodo="revisar", nota=f"no está en el JSON del padrón; la migración 0042 la da de alta con id_geo runtime (probable {alta[0]})",
                    cands=[f"{alta[0]}? {alta[2]} ({alta[1]}, alta 0042)"])
    # 3. fuzzy dentro del mismo departamento
    q = expand(loc_clean)
    best_alias = None
    for texto, id_geo, motivo, origen in alias_raw:
        if id_geo is None or dep_key(por_id[id_geo]["departamento"]) != dk:
            continue
        r = difflib.SequenceMatcher(None, q, expand(texto)).ratio()
        if best_alias is None or r > best_alias[0]:
            best_alias = (r, texto, por_id[id_geo])
    if best_alias and best_alias[0] >= 0.90:
        r, texto, g = best_alias
        return dict(metodo="fuzzy", geo=g, score=round(r * 100),
                    nota=f"fuzzy contra el alias '{texto}' (mismo departamento)",
                    cands=[f"{g['id_geo']} {g['localidad']} (alias '{texto}', {r*100:.0f})"])
    scored = {}
    for g in activos:
        if dep_key(g["departamento"]) != dk:
            continue
        best = 0.0
        for k in candidatos_localidad(g["localidad"]):
            for kk in (compact(k), expand(k)):
                r = difflib.SequenceMatcher(None, q, kk).ratio()
                r2 = difflib.SequenceMatcher(None, " ".join(sorted(q.split())), " ".join(sorted(kk.split()))).ratio()
                best = max(best, r, r2)
        scored[g["id_geo"]] = (best, g)
    ranking = sorted(scored.values(), key=lambda t: -t[0])[:3]
    cands = [f"{g['id_geo']} {g['localidad']} ({s*100:.0f})" for s, g in ranking]
    if not ranking:
        return dict(metodo="sin_match", nota="sin candidatos en el departamento")
    s1, g1 = ranking[0]
    s2 = ranking[1][0] if len(ranking) > 1 else 0
    sc = round(s1 * 100)
    if s1 >= 0.90 and s1 - s2 >= 0.10:
        return dict(metodo="fuzzy", geo=g1, score=sc, nota="fuzzy en el mismo departamento", cands=cands)
    if s1 >= 0.60:
        return dict(metodo="revisar", score=sc, nota="fuzzy con dudas — no se asume", cands=cands)
    return dict(metodo="sin_match", score=sc, nota="sin candidato razonable en el departamento", cands=cands)


# ── lectura de la planilla ───────────────────────────────────────────────────
def num(v):
    """Devuelve (valor_normalizado, nota). Números → int; '2,743' → 2743; '150M' → nota."""
    if v is None:
        return "", ""
    if isinstance(v, (int, float)):
        return (int(v) if float(v).is_integer() else v), ""
    s = str(v).strip()
    if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
        return int(s.replace(",", "")), ""
    if re.fullmatch(r"\d+(\.0+)?", s):
        return int(float(s)), ""
    if re.fullmatch(r"\d+(\.\d+)?\s*[Mm]", s):
        return "", s
    return s, ""

def txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip() if isinstance(v, str) else str(v)

wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
ws = wb["GENERAL"]
rows = list(ws.iter_rows(values_only=True))
header = rows[0]
fuera_de_rango = []
out, dep_actual, descartadas = [], None, []
for i, r in enumerate(rows[1:], start=2):
    r = list(r) + [None] * 13
    if all(v is None or str(v).strip() == "" for v in r):
        continue
    if any(v not in (None, "") for v in r[13:]):
        fuera_de_rango.append(i)
    dep_cell, prio, loc = r[0], r[1], r[2]
    if dep_cell and str(dep_cell).strip():
        dep_actual = str(dep_cell).strip()
    if loc is None or str(loc).strip() == "" or str(loc).strip().lower().startswith("http"):
        descartadas.append((i, r[:12]))
        continue
    loc_s = str(loc)
    res = resolver(dep_actual, loc_s)
    g = res.get("geo")
    notas = []
    hab, n_h = num(r[4])
    monto, n_m = num(r[7])
    ref, _ = num(r[8])
    mfs, n_f = num(r[9])
    if n_m: notas.append(f"MONTO: {n_m}")
    if n_f: notas.append(f"MONTO FIRMADO O SUGERIDO: {n_f}")
    out.append({
        "fila_origen": i,
        "departamento_planilla": dep_actual,
        "localidad_planilla": loc_s.strip(),
        "id_geo": g["id_geo"] if g else "",
        "departamento_oficial": g["departamento"] if g else "",
        "localidad_oficial": g["localidad"] if g else "",
        "metodo": res["metodo"],
        "score": res.get("score") if res.get("score") is not None else "",
        "prioridad": txt(prio),
        "tipo": txt(r[3]),
        "habitantes": hab,
        "visita_gobernador": txt(r[5]),
        "anuncio_gobernador": txt(r[6]),
        "monto": monto,
        "monto_nota": " | ".join(notas),
        "ref_gestor": ref,
        "monto_firmado_o_sugerido": mfs,
        "observacion": txt(r[10]),
        "col_extra": txt(r[11]),
        "col_extra_2": txt(r[12]),
        "nota_match": res.get("nota", ""),
        "candidatos": " · ".join(res.get("cands", [])) if res["metodo"] in ("revisar", "sin_match", "fuzzy") else "",
    })

OUT.mkdir(parents=True, exist_ok=True)
cols = list(out[0].keys())
with open(OUT / "cordon_cuneta_general.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(out)

# resumen para el README (json en scratchpad)
usados = collections.Counter(o["id_geo"] for o in out if o["id_geo"])
no_aparecen = [g for g in activos if g["id_geo"] not in usados]
summary = {
    "header": [str(h) for h in header],
    "filas": len(out),
    "descartadas": descartadas,
    "fuera_de_rango": fuera_de_rango,
    "metodos": collections.Counter(o["metodo"] for o in out),
    "dudosos": [o for o in out if o["metodo"] in ("revisar", "sin_match", "fuzzy")],
    "duplicados": {k: [o for o in out if o["id_geo"] == k] for k, c in usados.items() if c > 1},
    "no_aparecen": sorted(((g["departamento"], g["localidad"], g["id_geo"]) for g in no_aparecen)),
    "padron_activos": len(activos),
    "padron_total_json": len(padron),
    "alias_n": len(alias_raw),
    "exacto_con_nota": [o for o in out if o["metodo"] == "exacto" and o["nota_match"]],
    "alias_rows": [o for o in out if o["metodo"] == "alias"],
    "monto_nota": [o for o in out if o["monto_nota"]],
}
json.dump(summary, open(sys.argv[4], "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(summary["metodos"], summary["filas"], "descartadas", [d[0] for d in descartadas], "fuera", fuera_de_rango)
