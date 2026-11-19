"""Parseo puro (sin base) de la planilla "Gobierno" de la Privada del Gobernador
(spec-datos-externos-privada-gobernador.md §1 y §3).

Mismo contrato que `app/gob_fondos/parse.py`: cada `parsear_*` recibe los valores crudos de
una pestaña (`UNFORMATTED_VALUE`, las fechas llegan como número de serie) y devuelve
`(filas, anomalias)`. Columnas por encabezado; `EstructuraInvalida` si falta una obligatoria.
Las anomalías llevan número de fila o clave, nunca textos de la planilla.

Las columnas de personas llegan vacías (el sync no las pide, `COLUMNAS_EXCLUIDAS`) y ningún
parser las usa.
"""
import hashlib
import json
import re
from datetime import date, timedelta
from typing import Any

from app.gob_fondos.parse import _Enc, _contar, _texto
from app.gob_transferencias.parse import _filas, _limpio, es_error, fecha, monto
from app.gobierno.sync import normalizar_codigo

# Encabezados que nunca se leen, por pestaña (sin tildes, por prefijo; spec §6).
COLUMNAS_EXCLUIDAS = {
    "Gobierno": ("RESPONSABLE",),
    "FOCOM": ("ADMINISTRATIVO", "COORDINADOR", "REFERENTE", "OBSERVACIONES"),
    "ATP": ("REFERENTE", "TABLA DE COINCIDENCIAS"),
}

# 2026 sale de ATP Interno; el histórico solo trae lo anterior (spec §3.3).
CORTE_ATP_INTERNO = date(2026, 1, 1)
# Fechas de anuncio: la gestión arranca en diciembre de 2023; más allá de dos meses en el
# futuro es un typo (hay 2016 y 2027 en la planilla, spec §1.6).
_PRIMER_ANIO = 2023
_MARGEN_FUTURO = timedelta(days=60)


def _numero(raw: Any) -> float | None:
    valor, _invalido = monto(raw)
    return valor


def grado(raw: Any) -> float | None:
    """Grado de cumplimiento como fracción (1 = 100 %): `1`, `0.5`, `100`, `"100,00%"`."""
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if es_error(s):
            return None
        porcentaje = s.endswith("%")
        valor = _numero(s.rstrip("%").strip())
        if valor is None:
            return None
        return valor / 100 if porcentaje or valor > 1.5 else valor
    valor = float(raw)
    return valor / 100 if valor > 1.5 else valor


def si_no(raw: Any) -> bool | None:
    s = _limpio(raw).upper()
    return True if s in ("SI", "SÍ") else False if s == "NO" else None


_URL = re.compile(r"https?://\S+")


def url(raw: Any) -> str | None:
    """Primer link de la celda. "Link" (hipervínculo sin URL visible) no sirve: queda vacío."""
    m = _URL.search(str(raw or ""))
    return m.group(0) if m else None


# `$ 56 millones`, `60 millones`, `$1.500.000`, `mil millones`, `1.500 millones`. Un número
# sin `$` ni "millones" no cuenta (son cuadras, años, cantidades).
_MONTO_TEXTO = re.compile(
    r"(?P<signo>\$\s*)?(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(?P<escala>mil\s+millones|millones|millón|millon|mill\b|M\b)?",
    re.IGNORECASE,
)


def montos_en_texto(*textos: str | None) -> list[float]:
    """Montos en pesos mencionados en el anuncio, sin repetir, en orden de aparición."""
    out: list[float] = []
    for texto in textos:
        for m in _MONTO_TEXTO.finditer(texto or ""):
            escala = (m.group("escala") or "").lower()
            if not m.group("signo") and not escala:
                continue
            num = m.group("num")
            valor = float(num.replace(".", "").replace(",", ".")) if re.search(r"\.\d{3}", num) else float(num.replace(",", "."))
            if escala.startswith("mil "):
                valor *= 1e9
            elif escala:
                valor *= 1e6
            if valor >= 1000 and valor not in out:
                out.append(valor)
    return out


def _hash(fila: dict) -> str:
    campos = ("fecha_anuncio", "departamento", "localidad", "anuncio", "detalle", "estado", "indicador_seguimiento")
    return hashlib.sha256(json.dumps([str(fila.get(c)) for c in campos], ensure_ascii=False).encode()).hexdigest()


def _fecha_anuncio(raw: Any, hoy: date) -> tuple[date | None, str | None]:
    f = fecha(raw)
    if f is None:
        return None, None
    if f.year < _PRIMER_ANIO or f > hoy + _MARGEN_FUTURO:
        return None, f.isoformat()
    return f, None


# ── Anuncios ───────────────────────────────────────────────────────────────────────


def parsear_anuncios(valores: list[list[Any]], hoy: date | None = None) -> tuple[list[dict], list[dict]]:
    hoy = hoy or date.today()
    enc = _Enc(valores, ("ASCASU", "FECHA DE ANUNCIO", "DEPARTAMENTO", "LOCALIDAD", "ANUNCIO", "ESTADO"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    vistos: set[int] = set()
    fuera_de_rango = 0
    for n, fila in _filas(valores):
        clave = _numero(enc.get(fila, "ASCASU"))
        if clave is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        ascasu = int(clave)
        if ascasu in vistos:
            anomalias.append({"tipo": "fila_repetida", "codigo": str(ascasu)})
            continue
        vistos.add(ascasu)
        f_anuncio, f_texto = _fecha_anuncio(enc.get(fila, "FECHA DE ANUNCIO"), hoy)
        fuera_de_rango += f_texto is not None
        indicador = enc.get(fila, "INDICADOR DE SEGUIMIENTO")
        if isinstance(indicador, float) and indicador.is_integer():
            indicador = int(indicador)
        anuncio = _texto(enc.get(fila, "ANUNCIO"))
        detalle = _texto(enc.get(fila, "DETALLE DEL ANUNCIO"))
        salida = {
            "ascasu": ascasu,
            "fecha_carga": fecha(enc.get(fila, "FECHA DE CARGA")),
            "fecha_anuncio": f_anuncio,
            "fecha_anuncio_texto": f_texto,
            "fuente_url": url(enc.get(fila, "FUENTE DEL ANUNCIO")),
            "departamento": _texto(enc.get(fila, "DEPARTAMENTO"), 100),
            "localidad": _texto(enc.get(fila, "LOCALIDAD"), 150),
            "codigo_indec": None,  # lo resuelve el sync contra el nomenclador
            "ministerio": _texto(enc.get(fila, "MINISTERIO"), 100),
            "anuncio": anuncio,
            "detalle": detalle,
            "estado": _texto(enc.get(fila, "ESTADO"), 40),
            "linea_base": _numero(enc.get(fila, "LINEA BASE")),
            "valor_actual": _numero(enc.get(fila, "VALOR ACTUAL")),
            "grado_cumplimiento": grado(enc.get(fila, "GRADO DE CUMPLIMIENTO")),
            "comentarios": _texto(enc.get(fila, "COMENTARIOS")),
            "indicador_seguimiento": _texto(indicador, 40),
            "estado_seguimiento": None if es_error(enc.get(fila, "ESTADO GABRIEL")) else _texto(enc.get(fila, "ESTADO GABRIEL"), 40),
            "coinciden": si_no(enc.get(fila, "COINCIDEN")),
            "montos_mencionados": montos_en_texto(anuncio, detalle),
        }
        salida["hash_contenido"] = _hash(salida)
        filas.append(salida)
    _contar(anomalias, "fecha_fuera_de_rango", fuera_de_rango)
    return filas, anomalias


# ── FOCOM ──────────────────────────────────────────────────────────────────────────


def normalizar_id(raw: Any, sufijo: str) -> str | None:
    """`1782,-ATP` -> `1782-ATP`; `12` -> `12-ATP`. Sin número -> None."""
    m = re.search(r"\d+", str(raw or ""))
    return f"{int(m.group(0))}-{sufijo}" if m else None


def _ocurrencia(vistos: dict[str, int], clave: str) -> int:
    vistos[clave] = vistos.get(clave, 0) + 1
    return vistos[clave]


def parsear_focom(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Enc(valores, ("ID_FOCOM", "ID_LOC", "LOCALIDAD", "MONTO", "ESTADO"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    vistos: dict[str, int] = {}
    sin_datos = 0
    for n, fila in _filas(valores):
        # La planilla trae el ID precargado en miles de filas vacías: sin localidad ni monto no
        # hay convenio.
        if all(enc.get(fila, c) in (None, "") for c in ("ID_LOC", "LOCALIDAD", "MONTO")):
            sin_datos += 1
            continue
        id_focom = normalizar_id(enc.get(fila, "ID_FOCOM"), "FOCOM")
        if id_focom is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        importe, invalido = monto(enc.get(fila, "MONTO"))
        if invalido:
            anomalias.append({"tipo": "valor_invalido", "codigo": id_focom, "columna": "MONTO"})
        anio = _numero(enc.get(fila, "AÑO"))
        resolucion = enc.get(fila, "N° RESOLUCION")
        estado_obra = enc.get(fila, "ESTADO OBRA")
        filas.append({
            "id_focom": id_focom,
            "ocurrencia": _ocurrencia(vistos, id_focom),
            "expediente": _texto(enc.get(fila, "EXPTE"), 60),
            "convenio": _texto(enc.get(fila, "N° CONVENIO"), 60),
            "fecha_convenio": fecha(enc.get(fila, "FECHA CONVENIO")),
            # Algunas resoluciones vienen convertidas en fecha por la planilla: se descartan.
            "resolucion": None if isinstance(resolucion, (int, float)) else _texto(resolucion, 60),
            "departamento": _texto(enc.get(fila, "DEPARTAMENTO"), 100),
            "tipo": _texto(enc.get(fila, "TIPO"), 40),
            "codigo_indec": normalizar_codigo(enc.get(fila, "ID_LOC")),
            "localidad": _texto(enc.get(fila, "LOCALIDAD"), 150),
            "monto": importe,
            "concepto": _texto(enc.get(fila, "CONCEPTO")),
            "categoria": _texto(enc.get(fila, "CATEGORIA"), 60),
            "estado": (_texto(enc.get(fila, "ESTADO"), 40) or "").upper() or None,
            "fecha_pago": fecha(enc.get(fila, "FECHA PAGO")),
            "plazo_visacion": _texto(enc.get(fila, "COMPUTO PLAZO"), 60),
            "anio": int(anio) if anio else None,
            "estado_obra": None if es_error(estado_obra) else _texto(estado_obra, 40),
        })
    repetidos = sorted(k for k, v in vistos.items() if v > 1)
    if repetidos:
        anomalias.append({"tipo": "id_repetido", "codigos": repetidos})
    _contar(anomalias, "filas_sin_datos", sin_datos)
    return filas, anomalias


# ── ATP histórico ──────────────────────────────────────────────────────────────────


def parsear_atp_historico(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Solo filas anteriores a `CORTE_ATP_INTERNO`. De las posteriores deja en `anomalias` la
    cantidad y la suma, para el control contra ATP Interno (spec §3.3)."""
    enc = _Enc(valores, ("ID ATP", "LOCALIDAD", "FECHA", "MONTO"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    vistos: dict[str, int] = {}
    corrientes = 0
    suma_corrientes = 0.0
    for n, fila in _filas(valores):
        id_atp = normalizar_id(enc.get(fila, "ID ATP"), "ATP")
        f = fecha(enc.get(fila, "FECHA"))
        importe, invalido = monto(enc.get(fila, "MONTO"))
        if id_atp is None or f is None or importe is None or invalido:
            anomalias.append({"tipo": "fila_invalida", "fila": n})
            continue
        ocurrencia = _ocurrencia(vistos, id_atp)
        if f >= CORTE_ATP_INTERNO:
            corrientes += 1
            suma_corrientes += importe
            continue
        filas.append({
            "id_atp": id_atp,
            "ocurrencia": ocurrencia,
            "departamento": _texto(enc.get(fila, "DEPARTAMENTO"), 100),
            "localidad": _texto(enc.get(fila, "LOCALIDAD"), 150),
            "codigo_indec": None,  # lo resuelve el sync contra el nomenclador
            "fecha": f,
            "anio": f.year,
            "monto": importe,
        })
    repetidos = sorted(k for k, v in vistos.items() if v > 1)
    if repetidos:
        anomalias.append({"tipo": "id_repetido", "codigos": repetidos})
    anomalias.append({"tipo": "atp_desde_corte", "corte": CORTE_ATP_INTERNO.isoformat(), "filas": corrientes, "monto": round(suma_corrientes, 2)})
    return filas, anomalias

