"""Seed de `viv_geo_alias_manual` — las 17 vinculaciones manuales investigadas
en docs/files/spec-sync-atp-compromiso-gobernador.md §12.9 (16 resueltas
contra `viv_geo_localidades` real + 1, "Santiago Temple", confirmada como
ausente del padrón). Ver docs/files/spec-normalizacion-localidades.md §4.2.
"""
from app.geo.matching import normalize_name

# (texto_original, id_geo | None, motivo, origen)
_ALIAS_RAW: list[tuple[str, str | None, str, str]] = [
    ("Paso del Durazno", "443", "límite departamental — Sheet decía Juárez Celman, padrón real Río Cuarto", "atp"),
    ("Nicolás Bruzzone", "55", "una sola 'z' en el padrón (Nicolas Bruzone)", "atp"),
    ("Huanchilla", "92", "singular en el Sheet, plural en el padrón (Huanchillas)", "atp"),
    ("Capitán General Bernardo O'Higgins", "103", "abreviado en el padrón (Cap. Gral. B.Ohiggins)", "atp"),
    ("Colonia Barge", "105", "nombre distinto — confirmado por el usuario (Castro Urdiales - Colonia 25 de Mayo)", "atp"),
    ("General Levalle", "128", "con espacio en el padrón (General Le Valle)", "atp"),
    ("Villa Río Icho Cruz", "158", "nombre más corto en el padrón (Icho Cruz)", "atp"),
    ("La Carolina El Potosí", "170", "el padrón usa paréntesis, el Sheet no (La Carolina (El Potosí))", "atp"),
    ("Las Peñas Sud", "175", "Sud/Sur (Las Peñas Sur)", "atp"),
    ("Santa Catalina Holmberg", "182", "el padrón usa paréntesis (Santa Catalina (Est. Holmberg))", "atp"),
    ("Montecristo", "392", "con espacio en el padrón (Monte Cristo)", "atp"),
    ("Villa de María", "221", "nombre completo en el padrón (Villa de Maria de Rio Seco)", "atp"),
    ("San Javier y Yacanto", "261", "Yacanto es forma abreviada de San Javier — confirmado por el usuario", "atp"),
    ("Miramar de Ansenuza", "289", "nombre más corto en el padrón (Miramar)", "atp"),
    ("Saturnino María Laspiur", "296", "abreviado en el padrón (Saturnino M. Laspiur)", "atp"),
    ("Dalmacio Vélez", "324", "nombre completo en el padrón (Dalmacio Velez Sarsfield)", "atp"),
    ("James Craik", "327", "con 'c' en el padrón (James Craick)", "atp"),
    ("Santiago Temple", None, "localidad real (Río Segundo) confirmada ausente del padrón — no se inventa id_geo", "atp"),
]

ALIAS_MANUAL_SEED: list[dict] = [
    {
        "texto_normalizado": normalize_name(texto_original),
        "texto_original": texto_original,
        "id_geo": id_geo,
        "motivo": motivo,
        "origen": origen,
        "created_by": "migracion-spec-normalizacion-localidades",
    }
    for texto_original, id_geo, motivo, origen in _ALIAS_RAW
]

# Encontrados al investigar el reporte de "General Baldissera apareciendo dos
# veces" en Checklist Técnico (2026-09-28) — ver migración 0031. Typos reales
# de una palabra/letra, no accent-only.
_ALIAS_RAW_20260928: list[tuple[str, str | None, str, str]] = [
    ("GENERAL BALDISERA", "109", "una sola 's' en Córdoba Hogar (padrón: GENERAL BALDISSERA)", "cordoba_hogar"),
    ("LUXARDO", "291", "Córdoba Hogar omite 'Plaza' (padrón: PLAZA LUXARDO)", "cordoba_hogar"),
]

ALIAS_MANUAL_SEED_20260928: list[dict] = [
    {
        "texto_normalizado": normalize_name(texto_original),
        "texto_original": texto_original,
        "id_geo": id_geo,
        "motivo": motivo,
        "origen": origen,
        "created_by": "migracion-spec-normalizacion-localidades",
    }
    for texto_original, id_geo, motivo, origen in _ALIAS_RAW_20260928
]

# Investigación de los ~30 casos residuales sin resolver tras el primer
# backfill, pedida explícitamente por el usuario (2026-09-29) — ver migración
# 0032. Encontrados con el resolver real de producción, no una heurística.
# Nota: 7 pares adicionales resultaron ser duplicados dentro del propio
# padrón (misma localidad con dos id_geo, coordenadas a metros/pocos km) —
# esos NO se resuelven acá, quedan documentados para revisión manual del
# padrón (fuera de alcance de esta spec).
_ALIAS_RAW_20260929: list[tuple[str, str | None, str, str]] = [
    ("EUFRACIO LOZA", "558", "typo c/s (padrón: Eufrasio Loza) — RIO SECO", "gas_pit"),
    ("BRINKMANN", "269", "falta la 'c' (padrón: BRINCKMANN) — SAN JUSTO", "gas_pit"),
    ("CAPILLA DEL SITON", "339", "padrón usa 'DE', no 'DEL' (CAPILLA DE SITON) — TOTORAL", "gas_pit"),
    ("ESTACION GENERAL PAZ", "26", "confirmado por el usuario — estación de tren de GENERAL PAZ, COLÓN", "gas_pit"),
    ("VILLA QUILINO", "82", "confirmado por el usuario — 'Villa' es parte del nombre común de QUILINO, ISCHILÍN", "privada"),
    ("CHUÑ‘A", "553", "carácter espurio (U+2018) insertado en el dato de origen de Privada (padrón: Chuña) — ISCHILÍN", "privada"),
]

ALIAS_MANUAL_SEED_20260929: list[dict] = [
    {
        "texto_normalizado": normalize_name(texto_original),
        "texto_original": texto_original,
        "id_geo": id_geo,
        "motivo": motivo,
        "origen": origen,
        "created_by": "migracion-spec-normalizacion-localidades",
    }
    for texto_original, id_geo, motivo, origen in _ALIAS_RAW_20260929
]
