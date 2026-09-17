"""Normalización de nombres de departamento/localidad para matching best-effort
contra viv_geo_localidades. Compartido por app/cordon_cuneta/checklist_sync.py
y app/informes/aggregations.py — antes vivía duplicado solo en checklist_sync.
"""
import re
import unicodedata


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_name(s: str | None) -> str:
    if not s:
        return ""
    return strip_accents(s).strip().lower()


def candidatos_localidad(nombre: str | None) -> set[str]:
    """Nombres normalizados candidatos para un nombre de localidad que puede
    traer un alias entre paréntesis o separado por guion — ej.
    "VICUÑA MACKENNA (Est. Torres)", "DESPEÑADEROS (EstaciOn Lucas A. de
    Olmos)", "ELENA - MARIA ELENA". Superset de `{normalize_name(nombre)}`.

    Usado donde otra fuente puede nombrar la misma localidad con su alias en
    vez del nombre "principal" (ver `app/informe_localidades/service.py` y
    `services/svc-privada/scripts/cargar_habitantes_censo2022.py`, que usa
    la misma lógica del lado del censo)."""
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
