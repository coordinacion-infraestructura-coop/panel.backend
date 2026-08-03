"""Normalización de nombres de departamento/localidad para matching best-effort
contra viv_geo_localidades. Compartido por app/cordon_cuneta/checklist_sync.py
y app/informes/aggregations.py — antes vivía duplicado solo en checklist_sync.
"""
import unicodedata


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_name(s: str | None) -> str:
    if not s:
        return ""
    return strip_accents(s).strip().lower()
