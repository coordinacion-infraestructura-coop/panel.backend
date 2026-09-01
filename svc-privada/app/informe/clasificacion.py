"""Port de la vista BigQuery `v_informe_cooperativas` (Anexo A).

SÓLO aplica al informe de Cooperativas. NO es lógica transversal.
El spec hijo `spec-privada-informe-cooperativas-v2.md` reemplaza este regex por
clasificación sobre `categoria_id` estructurado (con doble corrida + sign-off).
"""
import re

MIN_COOPERATIVAS = "MIN_COOPERATIVAS_MUTUALES"

# 10 prioridades — primera coincidencia gana. (categoria, regex|None, es_min_coop, tema)
_RE = re.compile

_REGLAS = [
    ("CAT_INFRAESTRUCTURA_VIAL",
     _RE(r"cord[oó]n.{0,10}cuneta|cordon.{0,10}cuneta|\bcuneta\b|\badoquin|cordon\s+serran|cuneta\s+serran"),
     False, "Cordón Cuneta + Adoquinado"),
    ("CAT_OBRA_ELECTRICA_ENERGIA",
     _RE(r"kit\s*solar|kits?\s+solar|solar\s+kit"),
     False, "Kits Solares"),
    ("CAT_OBRA_ELECTRICA_ENERGIA",
     _RE(r"luminaria|alumbrado|\bled\b|pantalla.{0,10}(led|solar|\d+\s*w)|\bfarol"),
     False, "Luces LED"),
    ("CAT_OBRA_DE_GAS", None, False, "Gas"),
    # Bombeo Solar: categoría en {agua, eléctrica} + 'solar' + ('bomba'|'perforaci') — se maneja aparte
    (None,
     _RE(r"vivienda|habitacional|habitacionales|cordoba\s+hogar|programa.{0,10}viviend|unidades\s+habitacionales|vivienda\s+semilla|viviendas?\s+social|programa\s+habitacional"),
     False, "Vivienda"),
    (None,
     _RE(r"\blote[os]?\b|loteo|loteamiento|expropiaci[oó]n.{0,20}parcel|regulaci[oó]n.{0,10}domin|disposici[oó]n.{0,20}lote|plan.{0,10}lot|\bparcel[ao]\b|escrituraci[oó]n"),
     False, "Lotes"),
    ("CAT_OBRA_ELECTRICA_ENERGIA", None, False, "Infraestructura Eléctrica"),
    (None,
     _RE(r"fortalecimiento|fortalecim|pr[eé]stamo|cr[eé]dito|conformaci[oó]n.{0,20}cooperativa|proyecto.{0,15}textil|asociaciones\s+civiles|rendici[oó]n|estado\s+econ|deuda.{0,10}coop|mutual.{0,20}(prestacion|servicio)|m[aá]quinas\s+de\s+coser|cami[oó]n.{0,10}gr[uú]a"),
     True, "Préstamos y Fortalecimiento"),
]

_RE_SOLAR = _RE(r"solar")
_RE_BOMBEO = _RE(r"bomb[ao]|perforaci")


def es_ministerio_cooperativas(ministerio_agencia_id: str | None) -> bool:
    return ministerio_agencia_id == MIN_COOPERATIVAS


def tema_informe(categoria_general_id: str | None, detalle: str | None, ministerio_agencia_id: str | None) -> str | None:
    d = (detalle or "").lower()
    es_mc = es_ministerio_cooperativas(ministerio_agencia_id)

    # 1-3
    if categoria_general_id == "CAT_INFRAESTRUCTURA_VIAL" and _REGLAS[0][1].search(d):
        return "Cordón Cuneta + Adoquinado"
    if categoria_general_id == "CAT_OBRA_ELECTRICA_ENERGIA" and _REGLAS[1][1].search(d):
        return "Kits Solares"
    if categoria_general_id == "CAT_OBRA_ELECTRICA_ENERGIA" and _REGLAS[2][1].search(d):
        return "Luces LED"
    # 4
    if categoria_general_id == "CAT_OBRA_DE_GAS":
        return "Gas"
    # 5
    if categoria_general_id in ("CAT_AGUA_Y_SANEAMIENTO", "CAT_OBRA_ELECTRICA_ENERGIA") \
            and _RE_SOLAR.search(d) and _RE_BOMBEO.search(d):
        return "Bombeo Solar"
    # 6-7 (cualquier categoría)
    if _REGLAS[4][1].search(d):
        return "Vivienda"
    if _REGLAS[5][1].search(d):
        return "Lotes"
    # 8
    if categoria_general_id == "CAT_OBRA_ELECTRICA_ENERGIA":
        return "Infraestructura Eléctrica"
    # 9-10 (sólo ministerio de cooperativas)
    if es_mc and _REGLAS[7][1].search(d):
        return "Préstamos y Fortalecimiento"
    if es_mc:
        return "Otras Obras"
    return None


def entra_al_informe(categoria_general_id, detalle, ministerio_agencia_id) -> tuple[bool, str | None]:
    """Reproduce `WHERE es_ministerio_cooperativas = TRUE OR tema_informe IS NOT NULL`."""
    tema = tema_informe(categoria_general_id, detalle, ministerio_agencia_id)
    return (es_ministerio_cooperativas(ministerio_agencia_id) or tema is not None), tema
