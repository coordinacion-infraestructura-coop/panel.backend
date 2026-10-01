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

# svc-datos-externos / ETL de transferencias (ADR-025): 21 grupos sin id_geo
# tras la primera carga real a producción (Municipios+Comunas, julio 2026,
# 2568 filas). Investigados uno por uno contra el padrón real (2026-10-01):
# 16 con un único candidato claro (abreviatura/espaciado/singular-plural —
# mismo criterio que las tandas anteriores), 2 de confianza media (marcados
# abajo), y 3 que NO se fuerzan:
# - "KILOMETRO 658" (Río Primero) — mismo caso ya documentado en la migración
#   0032 (Gasífera encontró lo mismo), el padrón no tiene ningún "658", sólo
#   "KILOMETRO 691" (número distinto, no es un typo de un dígito).
# - "Santiago Temple" (Río Segundo) — mismo gap ya confirmado ausente del
#   padrón (migración original, origen "atp").
# - "TTOTAL Río Segundo" — no es una localidad real, es una fila de TOTAL del
#   PDF mal parseada como si fuera un municipio (ver nota en
#   app/transferencias/extract.py sobre anomalías conocidas del PDF fuente);
#   forzar un id_geo acá sería inventar un dato, el problema real está en el
#   parser de svc-datos-externos, no en el matching geográfico.
_ALIAS_RAW_20261001: list[tuple[str, str | None, str, str]] = [
    ("CAÑADA DEL SAUCE", "510", "el padrón antepone 'Villa' (VILLA CAÑADA DEL SAUCE) — CALAMUCHITA", "datos_externos"),
    ("LAS BAJADAS", "7", "nombre exacto en el padrón; ambiguo contra el alias de SOCONCHO (las Bajadas) en el mismo depto — se linkea al nombre literal, no al alias — CALAMUCHITA", "datos_externos"),
    ("PACHECO DE MELO", "96", "el padrón antepone 'Estacion' (ESTACION PACHECO DE MELO) — JUÁREZ CELMAN", "datos_externos"),
    ('LA CAROLINA "EL POTOSI"', "170", "mismo caso que el alias 'La Carolina El Potosí' ya existente, con comillas en vez de paréntesis — RÍO CUARTO", "datos_externos"),
    ("VILLA CANDELARIA NORTE", "220", "el padrón no tiene el sufijo 'Norte' (VILLA CANDELARIA) — único candidato con ese nombre en el depto, confianza media — RIO SECO", "datos_externos"),
    ("ARROYO LOS PATOS", "511", "al padrón le falta 'DE' (ARROYO DE LOS PATOS) — SAN ALBERTO", "datos_externos"),
    ("VILLA C.PAR. LOS REARTES", "560", "abreviado en el PDF (padrón: Villa Ciudad Parque los Reartes) — CALAMUCHITA", "datos_externos"),
    ("VILLA GRAL. BELGRANO", "17", "'Gral.' abrevia 'General' en el PDF (padrón: VILLA GENERAL BELGRANO) — CALAMUCHITA", "datos_externos"),
    ("SAN MARCOS SIERRAS", "45", "plural en el PDF, singular en el padrón (SAN MARCOS SIERRA) — CRUZ DEL EJE", "datos_externos"),
    ("CAP. GRAL. B. O'HIGGINS", "103", "mismo caso que el alias 'Capitán General Bernardo O'Higgins' ya existente, abreviado distinto — MARCOS JUÁREZ", "datos_externos"),
    ("SANTA MARIA", "152", "el PDF omite 'DE PUNILLA' (padrón: SANTA MARIA DE PUNILLA) — PUNILLA", "datos_externos"),
    ("YCHO CRUZ", "158", "'Y' por 'I' en el PDF (padrón: ICHO CRUZ) — PUNILLA", "datos_externos"),
    ("ALCIRA GIGENA", "161", "separador distinto en el padrón (ALCIRA - EST. GIGENA) — RÍO CUARTO", "datos_externos"),
    ("SANTA ROSA DE RIO PRIMERO", "206", "el padrón registra la cabecera del depto sólo como 'Rio Primero' (nombre oficial completo es Santa Rosa de Río Primero) — confianza media — RÍO PRIMERO", "datos_externos"),
    ("SEBASTIAN EL CANO", "219", "con espacio en el PDF (padrón: SEBASTIAN ELCANO) — RIO SECO", "datos_externos"),
    ("COSTASACATE", "228", "sin espacio en el PDF (padrón: COSTA SACATE) — RÍO SEGUNDO", "datos_externos"),
    ("LASPIUR", "296", "mismo caso que el alias 'Saturnino María Laspiur' ya existente, forma corta — SAN JUSTO", "datos_externos"),
    ("VILLA PQUE.SANTA ANA", "317", "'Pque.' abrevia 'Parque' en el PDF (padrón: VILLA PARQUE SANTA ANA) — SANTA MARÍA", "datos_externos"),
    ("KILOMETRO 658", None, "mismo caso ya documentado en la migración 0032 (Gasífera) — el padrón sólo tiene 'Kilometro 691', número distinto, no se inventa un id_geo — RÍO PRIMERO", "datos_externos"),
    ("Santiago Temple", None, "mismo gap ya confirmado ausente del padrón (ver alias original, origen atp) — RÍO SEGUNDO", "datos_externos"),
]

ALIAS_MANUAL_SEED_20261001: list[dict] = [
    {
        "texto_normalizado": normalize_name(texto_original),
        "texto_original": texto_original,
        "id_geo": id_geo,
        "motivo": motivo,
        "origen": origen,
        "created_by": "migracion-sync-transferencias-datos-externos",
    }
    for texto_original, id_geo, motivo, origen in _ALIAS_RAW_20261001
]
