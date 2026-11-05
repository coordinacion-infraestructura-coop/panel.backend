"""Carga del glosario y helpers puros de normalización (spec §3.1, §4, §5.1)."""
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import yaml

_RUTA = Path(__file__).with_name("glosario.yaml")


@lru_cache(maxsize=1)
def glosario() -> dict:
    with _RUTA.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalizar(s: str | None) -> str:
    """Mismo criterio que svc-vivienda `geo/matching.normalize_name`."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", sin_acentos(s).strip().lower())


def normalizar_departamento(s: str | None) -> str:
    """Mismo criterio que svc-vivienda `geo/matching.normalize_departamento`."""
    n = normalizar(s)
    n = re.sub(r"\bgeneral\b", "gral", n)
    return re.sub(r"\bpresidente\b", "pte", n)


def estado_normalizado(familia: str, estado_origen: str | None) -> str:
    """Mapea un estado de origen a la escala común (spec §5.1) según `mapeo_estados.<familia>`."""
    cfg = glosario()["mapeo_estados"][familia]
    if not estado_origen:
        return "Sin iniciar"
    exactos = cfg.get("exactos") or {}
    if estado_origen in exactos:
        return exactos[estado_origen]
    texto = normalizar(estado_origen)
    for regla in cfg.get("reglas") or []:
        if re.search(regla["patron"], texto):
            return regla["estado"]
    return cfg["por_defecto"]


# ── Enmascarado de datos personales en texto libre (spec §4) ─────────────────
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# DNI: 7-8 dígitos, con o sin puntos (12.345.678 / 12345678). CUIT: 20-12345678-9.
_CUIT = re.compile(r"\b\d{2}-?\d{7,8}-?\d\b")
# No enmascara montos ("$ 1.500.000").
_DNI = re.compile(r"(?<!\$)(?<!\$ )\b\d{1,2}\.?\d{3}\.?\d{3}\b")
# Teléfonos: 6+ dígitos con separadores opcionales y prefijos (+54 9 351 555-1234, 0351-4567890).
_TEL = re.compile(r"(?<!\$)(?<!\$ )(\+?\d[\d\s().-]{6,}\d)")


def enmascarar(texto: str | None) -> str | None:
    if not texto:
        return texto
    t = _EMAIL.sub("[email]", texto)
    t = _CUIT.sub("[cuit]", t)
    t = _DNI.sub("[dni]", t)

    def _tel(m: re.Match) -> str:
        digitos = re.sub(r"\D", "", m.group(1))
        return "[teléfono]" if len(digitos) >= 7 else m.group(1)

    return _TEL.sub(_tel, t)


def url_ficha(departamento: str | None, localidad: str | None) -> str | None:
    if not departamento or not localidad:
        return None
    return f"/resumen-territorial/{quote(departamento, safe='')}/{quote(localidad, safe='')}"


def programa_info(codigo: str) -> dict:
    return glosario()["programas"][codigo]
