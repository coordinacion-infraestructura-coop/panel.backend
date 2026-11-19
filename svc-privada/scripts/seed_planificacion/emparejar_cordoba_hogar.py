"""Empareja la única pestaña ('Hoja 1') de 'Cordoba Hogar OK.xlsx' contra el
padrón viv_geo_localidades reconstruido desde el repo (docs/data/geo_localidades.json
+ migraciones 0033/0042) y los alias de viv_geo_alias_manual (seed_data.py + 0036).
El resolver (réplica de app/geo/matching.py) es copia literal del de
emparejar_cordon_cuneta.py; cambia solo la lectura de la planilla y se suman las
correcciones confirmadas por el usuario (CONFIRMADOS / forzar_revisar).

La planilla de CH no tiene columna de prioridad: la prioridad está en el COLOR de
relleno de la fila (columna B). Se exporta el color (nombre + hex) y la prioridad
propuesta según la escala de la spec (§4.3).

Uso:
    python -I emparejar_cordoba_hogar.py <xlsx> <repo_root> <out_dir> <resumen.json>
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



# ── correcciones confirmadas por el usuario (2026-11-19, valen para CC y CH) ──
# (departamento con dep_key, localidad con compact o expand) → id_geo
CONFIRMADOS = {
    ("calamuchita", "parque calmayo"): ("2", "confirmado por el usuario 2026-11-19 (igual que CC)"),
    ("rio primero", "villa sta rosa de rio i"): ("208", "confirmado por el usuario 2026-11-19 (igual que CC); "
                                                 "el alias 0034 SANTA ROSA DE RIO PRIMERO -> 206 es incorrecto"),
    ("rio primero", "villa santa rosa de rio i"): ("208", "confirmado por el usuario 2026-11-19 (igual que CC); "
                                                   "el alias 0034 SANTA ROSA DE RIO PRIMERO -> 206 es incorrecto"),
    ("rio primero", "villa santa rosa de rio primero"): ("208", "confirmado por el usuario 2026-11-19; "
                                                         "el alias 0034 -> 206 es incorrecto"),
}
# Fuzzy ya revisados y aceptados por el usuario en CC (texto compactado de la fuente).
FUZZY_CONFIRMADOS = {"riobamba", "san jeronimo", "bouwer", "villa caros paz", "rosario de saladillo"}


def forzar_revisar(loc):
    """Kilómetro 658 / Pedro E. Vivas: no fusionar, siempre a revisión."""
    c = compact(loc)
    return ("658" in c) or ("vivas" in c)


def resolver_ch(dep, loc):
    dk = dep_key(dep)
    for k in [(dk, compact(loc)), (dk, expand(loc))]:
        if k in CONFIRMADOS:
            id_geo, nota = CONFIRMADOS[k]
            return dict(metodo="confirmado_usuario", geo=por_id[id_geo], score="", nota=nota)
    res = resolver(dep, loc)
    if forzar_revisar(loc):
        g = res.get("geo")
        cands = [f"{g['id_geo']} {g['localidad']} ({res['metodo']})"] if g else list(res.get("cands", []))
        alta = ALTAS_PROBABLES.get(normalize_name("KILÓMETRO 658"))
        cands.append(f"{alta[0]}? {alta[2]} ({alta[1]}, alta 0042)")
        return dict(metodo="revisar", score=res.get("score"), cands=cands,
                    nota="KILÓMETRO 658 / PEDRO E. VIVAS: posible duplicado en el padrón, lo revisa el usuario a mano "
                         f"(el resolver daba '{res['metodo']}')")
    g = res.get("geo")
    if g and g["id_geo"] == "241":  # AGUA DE ORO es de Colón (22), nunca 241 de Río Segundo
        return dict(metodo="revisar", score=res.get("score"), cands=["22 AGUA DE ORO (COLÓN)"],
                    nota="AGUA DE ORO es de Colón (22); 241 es un error del padrón")
    if res["metodo"] == "fuzzy" and compact(loc) in FUZZY_CONFIRMADOS:
        res["nota"] = res.get("nota", "") + "; fuzzy confirmado por el usuario en CC"
    return res


# ── lectura de la planilla ───────────────────────────────────────────────────
# Escala de prioridades de la spec §4.3: 1 celeste, 2 verde, 3 naranja,
# 4 amarillo, 5 rojo, X desestimado. Violeta y gris no están en la escala.
COLORES = {
    "FF00B0F0": ("celeste", "1"),
    "FF92D050": ("verde", "2"),
    "FFFFC000": ("naranja", "3"),
    "FFFFFF00": ("amarillo", "4"),
    "FFFF0000": ("rojo", "5"),
    "FF674EA7": ("violeta", "?"),
    "FFCCCCCC": ("gris", "?"),
}


def fill_hex(c):
    f = c.fill
    if f is None or f.fill_type is None:
        return ""
    fg = f.fgColor
    return fg.rgb if fg.type == "rgb" else f"{fg.type}:{fg.theme if fg.type == 'theme' else fg.indexed}"


def num(v):
    """Números → int; '2.743'/'2,743' → 2743; '150M' → 150000000 (confirmado por el usuario)."""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else v
    s = str(v).strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        return int(re.sub(r"[.,]", "", s))
    if re.fullmatch(r"\d+(\.0+)?", s):
        return int(float(s))
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*[Mm]", s)
    if m:
        return int(round(float(m.group(1).replace(",", ".")) * 1_000_000))
    return s


def txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


wb = openpyxl.load_workbook(XLSX, data_only=True)  # sin read_only: hacen falta los rellenos
ws = wb.worksheets[0]
HDR_ROW = 2
header = [c.value for c in ws[HDR_ROW]]
out, dep_actual, descartadas, fuera_de_rango = [], None, [], []
for row in ws.iter_rows(min_row=HDR_ROW + 1, max_row=ws.max_row):
    i = row[0].row
    r = [c.value for c in row] + [None] * 10
    if any(c.value not in (None, "") for c in row[10:]):
        fuera_de_rango.append(i)
    if all(v is None or str(v).strip() == "" for v in r[:10]):
        continue
    if r[0] and str(r[0]).strip():
        dep_actual = str(r[0]).strip()
    loc = r[1]
    if loc is None or str(loc).strip() == "" or str(loc).strip().lower().startswith("http"):
        descartadas.append((i, [txt(x) for x in r[:10]]))
        continue
    loc_s = str(loc).strip()
    res = resolver_ch(dep_actual, loc_s)
    g = res.get("geo")
    hx, hx_hab = fill_hex(row[1]), fill_hex(row[3])
    nombre, codigo = COLORES.get(hx, (hx or "sin color", "?"))
    out.append({
        "fila_origen": i,
        "departamento_planilla": dep_actual,
        "localidad_planilla": loc_s,
        "id_geo": g["id_geo"] if g else "",
        "departamento_oficial": g["departamento"] if g else "",
        "localidad_oficial": g["localidad"] if g else "",
        "metodo": res["metodo"],
        "score": res.get("score") if res.get("score") is not None else "",
        "prioridad_color": nombre,
        "prioridad_color_hex": hx,
        "prioridad_propuesta": codigo,
        "color_hab": COLORES.get(hx_hab, (hx_hab, ""))[0] if hx_hab != hx else "",
        "tipo": txt(r[2]),
        "habitantes": num(r[3]),
        "visita_gobernador": txt(r[4]),
        "anuncio_gobernador": txt(r[5]),
        "convenio_vivienda": txt(r[6]),
        "ref_gestor": num(r[7]),
        "cantidad_viviendas": num(r[8]),
        "observacion": txt(r[9]),
        "nota_match": res.get("nota", ""),
        "candidatos": " · ".join(res.get("cands", [])) if res["metodo"] in ("revisar", "sin_match", "fuzzy") else "",
    })

OUT.mkdir(parents=True, exist_ok=True)
cols = list(out[0].keys())
with open(OUT / "cordoba_hogar_general.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(out)

usados = collections.Counter(o["id_geo"] for o in out if o["id_geo"])
no_aparecen = [g for g in activos if g["id_geo"] not in usados]
summary = {
    "header": [str(h) for h in header],
    "filas": len(out),
    "descartadas": descartadas,
    "fuera_de_rango": fuera_de_rango,
    "metodos": collections.Counter(o["metodo"] for o in out),
    "colores": collections.Counter(o["prioridad_color"] for o in out),
    "color_x_convenio": collections.Counter(f"{o['prioridad_color']}|conv={o['convenio_vivienda']}" for o in out),
    "color_x_anuncio": collections.Counter(f"{o['prioridad_color']}|anuncio={o['anuncio_gobernador']}" for o in out),
    "color_x_visita": collections.Counter(f"{o['prioridad_color']}|visita={o['visita_gobernador']}" for o in out),
    "color_hab_distinto": [(o["fila_origen"], o["localidad_planilla"], o["prioridad_color"], o["color_hab"]) for o in out if o["color_hab"]],
    "dudosos": [o for o in out if o["metodo"] in ("revisar", "sin_match", "fuzzy", "confirmado_usuario")],
    "duplicados": {k: [o for o in out if o["id_geo"] == k] for k, c in usados.items() if c > 1},
    "no_aparecen": sorted(((g["departamento"], g["localidad"], g["id_geo"]) for g in no_aparecen)),
    "padron_activos": len(activos),
    "padron_total_json": len(padron),
    "alias_n": len(alias_raw),
    "exacto_con_nota": [o for o in out if o["metodo"] == "exacto" and o["nota_match"]],
    "alias_rows": [o for o in out if o["metodo"] == "alias"],
}
json.dump(summary, open(sys.argv[4], "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
sys.stdout.reconfigure(encoding="utf-8")
print(summary["metodos"], summary["filas"], "descartadas", [d[0] for d in descartadas], "fuera", fuera_de_rango)
