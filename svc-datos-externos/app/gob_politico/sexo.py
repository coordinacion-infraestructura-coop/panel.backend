"""Género del intendente o intendenta por localidad, para el filtro de Planificación de Privada
(spec-padron-politico-gobierno-privada.md §2.4, spec-privada-planificacion-programas.md §5.1).

Fuente oficial: `ganador_sexo` de las municipales 2023 (`ext_gob_eleccion_municipal`). Solo vale
si quien ganó es quien está hoy: se comparan las palabras de los dos nombres, admitiendo
diferencias mínimas de escritura. Donde no
coinciden (interinos, reemplazos) se deduce del nombre y queda marcado `nombre`, para revisarlo
a mano:

1. "(INTERINA)" / "(INTERINO)" en el nombre.
2. Votos de las palabras del nombre según los ganadores 2023 con sexo conocido. Una palabra vota
   solo si aparece al menos 2 veces y siempre con el mismo sexo; así los apellidos, que se
   reparten entre los dos, no votan.

Es el único dato político que sale de esta base hacia Privada además de intendente y partido:
sin celular, contacto ni resultados (excepción autorizada por el usuario el 2026-11-24 a la
regla de spec-datos-externos-fase6-politico.md §5).
"""
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from app.gob_politico.parse import clave_nombre

ELECCION_2023 = "eleccion_2023"
NOMBRE = "nombre"
SEXOS = ("F", "M")


def _palabras(nombre: str | None) -> set[str]:
    return {p for p in clave_nombre(re.sub(r"[(),]", " ", nombre or "")).split() if len(p) >= 3}


def misma_persona(a: set[str], b: set[str]) -> bool:
    """Alguna palabra en común, aunque esté escrita apenas distinto (EDGARD / EDGAR)."""
    return bool(a & b) or any(SequenceMatcher(None, x, y).ratio() >= 0.85 for x in a for y in b)


def votos_por_palabra(ganadores: list[tuple[str | None, str | None]]) -> dict[str, str]:
    """{palabra: sexo} con las palabras que siempre aparecen con el mismo sexo (al menos 2 veces)."""
    conteo: dict[str, Counter] = defaultdict(Counter)
    for nombre, sexo in ganadores:
        if sexo in SEXOS:
            for p in _palabras(nombre):
                conteo[p][sexo] += 1
    return {p: next(iter(c)) for p, c in conteo.items() if len(c) == 1 and sum(c.values()) >= 2}


def sexo_intendente(
    intendente: str | None, ganador_nombre: str | None, ganador_sexo: str | None, votos: dict[str, str]
) -> tuple[str | None, str | None]:
    """(sexo `F`/`M` o None, origen `eleccion_2023`/`nombre` o None)."""
    if not intendente:
        return None, None
    palabras = _palabras(intendente)
    if ganador_sexo in SEXOS and misma_persona(palabras, _palabras(ganador_nombre)):
        return ganador_sexo, ELECCION_2023
    if "INTERINA" in palabras:
        return "F", NOMBRE
    if "INTERINO" in palabras:
        return "M", NOMBRE
    c = Counter(votos[p] for p in palabras if p in votos)
    if len(c) == 1:
        return next(iter(c)), NOMBRE
    return None, None
