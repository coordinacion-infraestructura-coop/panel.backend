"""Parseo puro (sin base) de las planillas de transferencias de Gobierno
(spec-datos-externos-fase2-transferencias.md §1 y §3).

Cada `parsear_*` recibe los valores crudos de la pestaña (leídos con `UNFORMATTED_VALUE`, así
que las fechas llegan como número de serie) y devuelve `(filas, anomalias)`. Las columnas se
buscan por encabezado; si falta una obligatoria se lanza `EstructuraInvalida` y la fuente no se
aplica. Una fila inválida se descarta y queda como anomalía, con código de localidad y columna,
nunca con el valor.
"""
import re
from datetime import date, timedelta
from typing import Any

from app.gobierno.sync import normalizar_codigo

_EPOCH_SHEETS = date(1899, 12, 30)

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


class EstructuraInvalida(Exception):
    """La pestaña no tiene la forma esperada (faltan encabezados obligatorios)."""


# ── Celdas ────────────────────────────────────────────────────────────────────────


def norm_header(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw if raw is not None else "")).strip().upper()


def _limpio(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw if raw is not None else "")).strip()


def es_error(raw: Any) -> bool:
    """Celda con error de fórmula: `#####`, `#N/A`, `#REF!`, `#DIV/0!`."""
    return isinstance(raw, str) and raw.strip().startswith("#")


def monto(raw: Any) -> tuple[float | None, bool]:
    """`(valor, invalido)`. Admite negativos (ajustes, neto resultante). Vacío o `NA` ->
    `(None, False)`; error de fórmula o texto no numérico -> `(None, True)`."""
    if raw is None or isinstance(raw, bool):
        return None, False
    if isinstance(raw, (int, float)):
        return (None, True) if raw != raw else (float(raw), False)
    s = str(raw).strip()
    if not s or s.upper() in ("NA", "N/A", "N/C", "-"):
        return None, False
    if es_error(s):
        return None, True
    s = s.replace("$", "").replace(" ", "")
    for candidato in (s, s.replace(".", "").replace(",", ".")):
        try:
            return float(candidato), False
        except ValueError:
            continue
    return None, True


def entero(raw: Any) -> tuple[int | None, bool]:
    valor, invalido = monto(raw)
    return (int(round(valor)) if valor is not None else None), invalido


def fecha(raw: Any) -> date | None:
    """Número de serie de Sheets, o texto `d/m/aaaa`."""
    if isinstance(raw, bool) or raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        return _EPOCH_SHEETS + timedelta(days=int(raw)) if raw > 0 else None
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", str(raw))
    if not m:
        return None
    d, mo, a = (int(x) for x in m.groups())
    try:
        return date(a + 2000 if a < 100 else a, mo, d)
    except ValueError:
        return None


def mes_de(raw: Any) -> int | None:
    """Mes (1-12) de una celda de mes: fecha serial (solo cuenta el mes, el año sale de otra
    columna), `01 - enero`, `enero` u `octubre 2023`."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        f = fecha(raw)
        return f.month if f else None
    s = _limpio(raw).lower()
    m = re.match(r"^(\d{1,2})\b", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1))
    for nombre, n in _MESES.items():
        if s.startswith(nombre) or f" {nombre}" in f" {s}":
            return n
    return None


def periodo_de(raw: Any) -> date | None:
    """Primer día del mes de una celda `MES` con año propio (FODEMEP): fecha serial u
    `octubre 2023`."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        f = fecha(raw)
        return date(f.year, f.month, 1) if f else None
    s = _limpio(raw).lower()
    m = re.match(r"^([a-z]+)\s+(\d{4})$", s)
    if m and m.group(1) in _MESES:
        return date(int(m.group(2)), _MESES[m.group(1)], 1)
    return None


def quincena_de(raw: Any) -> int | None:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return int(raw) if raw in (1, 2) else None
    m = re.match(r"^\s*([12])", str(raw or ""))
    return int(m.group(1)) if m else None


# ── Encabezados ───────────────────────────────────────────────────────────────────


class _Encabezados:
    """Posición de cada encabezado normalizado (primera aparición) y nombre original."""

    def __init__(self, valores: list[list[Any]], obligatorios: tuple[str, ...]):
        if not valores:
            raise EstructuraInvalida("la pestaña está vacía")
        self.crudos = [_limpio(h) for h in valores[0]]
        self.norm = [norm_header(h) for h in valores[0]]
        self.idx: dict[str, int] = {}
        for i, h in enumerate(self.norm):
            if h and h not in self.idx:
                self.idx[h] = i
        faltantes = [h for h in obligatorios if h not in self.idx]
        if faltantes:
            raise EstructuraInvalida(f"faltan encabezados: {', '.join(faltantes)}")

    def get(self, fila: list[Any], nombre: str) -> Any:
        i = self.idx.get(nombre)
        return fila[i] if i is not None and i < len(fila) else None


def _vacia(fila: list[Any]) -> bool:
    return not any(c not in (None, "") for c in fila)


def _filas(valores: list[list[Any]]):
    for n, fila in enumerate(valores[1:], start=2):
        if not _vacia(fila):
            yield n, fila


def _montos(enc: _Encabezados, fila: list[Any], campos: dict[str, str], codigo: str, anomalias: list[dict]) -> dict:
    out: dict[str, Any] = {}
    for encabezado, campo in campos.items():
        valor, invalido = monto(enc.get(fila, encabezado))
        out[campo] = valor
        if invalido:
            anomalias.append({"tipo": "valor_invalido", "codigo": codigo, "columna": encabezado})
    return out


def _descuentos(
    enc: _Encabezados, fila: list[Any], desde: int, hasta: int, codigo: str, anomalias: list[dict]
) -> dict[str, float]:
    """Toda columna con encabezado entre `desde` y `hasta` (inclusive) es un descuento,
    con su nombre original. Un encabezado repetido suma ` (2)` para no pisar al primero."""
    out: dict[str, float] = {}
    for i in range(desde, hasta + 1):
        nombre = enc.crudos[i] if i < len(enc.crudos) else ""
        if not nombre:
            continue
        clave = nombre
        k = 2
        while clave in out:
            clave = f"{nombre} ({k})"
            k += 1
        valor, invalido = monto(fila[i] if i < len(fila) else None)
        if invalido:
            anomalias.append({"tipo": "valor_invalido", "codigo": codigo, "columna": nombre})
        out[clave] = valor or 0.0
    return out


def _codigo(enc: _Encabezados, fila: list[Any], n: int, anomalias: list[dict]) -> str | None:
    codigo = normalizar_codigo(enc.get(fila, "ID_LOC"))
    if codigo is None:
        anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
    return codigo


def _sin_repetir(filas: list[dict], clave: tuple[str, ...], anomalias: list[dict]) -> list[dict]:
    vistos: set[tuple] = set()
    out = []
    for f in filas:
        k = tuple(f[c] for c in clave)
        if k in vistos:
            anomalias.append({"tipo": "fila_repetida", "codigo": f["codigo_indec"]})
            continue
        vistos.add(k)
        out.append(f)
    return out


# ── COPA ──────────────────────────────────────────────────────────────────────────

_COPA_OBLIGATORIOS = (
    "ID_LOC", "QUINCENA", "MES", "AÑO", "FECHA DE PAGO", "TOTAL COP. MUNICIPIOS",
    "NETO RESULTANTE", "NETO A TRANSFERIR", "CAJA DE JUBILACIONES", "APROSS", "VARIOS",
)
_COPA_MONTOS = {
    "TOTAL COP. MUNICIPIOS": "bruto",
    "AJUSTE": "ajuste",
    "TOTAL AJUSTADO": "total_ajustado",
    "NETO RESULTANTE": "neto_resultante",
    "NETO A TRANSFERIR": "neto_a_transferir",
}


def parsear_copa(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Encabezados(valores, _COPA_OBLIGATORIOS)
    desde, hasta = enc.idx["CAJA DE JUBILACIONES"], enc.idx["VARIOS"]
    if hasta < desde:
        raise EstructuraInvalida("las columnas de descuento no están entre Caja de Jubilaciones y Varios")
    nombre_caja, nombre_apross = enc.crudos[desde], enc.crudos[enc.idx["APROSS"]]
    filas: list[dict] = []
    anomalias: list[dict] = []
    for n, fila in _filas(valores):
        codigo = _codigo(enc, fila, n, anomalias)
        if codigo is None:
            continue
        anio, _ = entero(enc.get(fila, "AÑO"))
        mes = mes_de(enc.get(fila, "MES"))
        quincena = quincena_de(enc.get(fila, "QUINCENA"))
        if not anio or not mes or not quincena:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        descuentos = _descuentos(enc, fila, desde, hasta, codigo, anomalias)
        id_copa, _ = entero(enc.get(fila, "CODIGO"))
        indice, _ = monto(enc.get(fila, "INDICE"))
        filas.append({
            "codigo_indec": codigo,
            "anio": anio,
            "mes": mes,
            "quincena": quincena,
            "fecha_pago": fecha(enc.get(fila, "FECHA DE PAGO")),
            "id_copa": id_copa,
            "indice": indice,
            **_montos(enc, fila, _COPA_MONTOS, codigo, anomalias),
            "caja_jubilaciones": descuentos.get(nombre_caja),
            "apross": descuentos.get(nombre_apross),
            "descuentos": descuentos,
        })
    return _sin_repetir(filas, ("codigo_indec", "anio", "mes", "quincena"), anomalias), anomalias


# ── FOFINDES ──────────────────────────────────────────────────────────────────────

_FOFINDES_OBLIGATORIOS = ("ID_LOC", "MES", "AÑO", "FECHA DE PAGO", "FOFINDES", "NETO RESULTANTE", "NETO A TRANSFERIR")
_FOFINDES_MONTOS = {
    "TOTAL PARTE VARIABLEFOFINDES": "total_parte_variable",
    "EXCEDENTE 30%": "excedente_30",
    "EXCEDENTE 70%": "excedente_70",
    "FOFINDES": "bruto",
    "NETO RESULTANTE": "neto_resultante",
    "NETO A TRANSFERIR": "neto_a_transferir",
}


def parsear_fofindes(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Encabezados(valores, _FOFINDES_OBLIGATORIOS)
    # Descuentos: entre `FOFINDES` y la primera `NETO RESULTANTE`. Las columnas repetidas que
    # vienen después del neto no se leen (spec §1.2 y §8.3).
    desde, hasta = enc.idx["FOFINDES"] + 1, enc.idx["NETO RESULTANTE"] - 1
    filas: list[dict] = []
    anomalias: list[dict] = []
    for n, fila in _filas(valores):
        codigo = _codigo(enc, fila, n, anomalias)
        if codigo is None:
            continue
        anio, _ = entero(enc.get(fila, "AÑO"))
        mes = mes_de(enc.get(fila, "MES"))
        if not anio or not mes:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        filas.append({
            "codigo_indec": codigo,
            "anio": anio,
            "mes": mes,
            "fecha_pago": fecha(enc.get(fila, "FECHA DE PAGO")),
            **_montos(enc, fila, _FOFINDES_MONTOS, codigo, anomalias),
            "descuentos": _descuentos(enc, fila, desde, hasta, codigo, anomalias) if hasta >= desde else {},
        })
    return _sin_repetir(filas, ("codigo_indec", "anio", "mes", "fecha_pago"), anomalias), anomalias


# ── FODEMEP ───────────────────────────────────────────────────────────────────────

_FODEMEP_OBLIGATORIOS = ("ID_LOC", "MES", "FECHA DE PAGO", "TOTAL FODEEMEP", "ACUMULADO", "NETO A TRANSFERIR")
_FODEMEP_MONTOS = {"TOTAL FODEEMEP": "presupuestado", "ACUMULADO": "acumulado", "NETO A TRANSFERIR": "neto_a_transferir"}


def parsear_fodemep(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Encabezados(valores, _FODEMEP_OBLIGATORIOS)
    filas: list[dict] = []
    anomalias: list[dict] = []
    for n, fila in _filas(valores):
        codigo = _codigo(enc, fila, n, anomalias)
        if codigo is None:
            continue
        periodo = periodo_de(enc.get(fila, "MES"))
        if periodo is None:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        filas.append({
            "codigo_indec": codigo,
            "periodo": periodo,
            "fecha_pago": fecha(enc.get(fila, "FECHA DE PAGO")),
            **_montos(enc, fila, _FODEMEP_MONTOS, codigo, anomalias),
        })
    return _sin_repetir(filas, ("codigo_indec", "periodo"), anomalias), anomalias


def parsear_fodemep_estado(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Encabezados(valores, ("ID_LOC", "ESTADO", "SALDO DE GESTION"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    for n, fila in _filas(valores):
        codigo = _codigo(enc, fila, n, anomalias)
        if codigo is None:
            continue
        estado = _limpio(enc.get(fila, "ESTADO")).upper() or None
        saldo, invalido = monto(enc.get(fila, "SALDO DE GESTION"))
        if invalido:
            anomalias.append({"tipo": "valor_invalido", "codigo": codigo, "columna": "SALDO DE GESTION"})
        filas.append({"codigo_indec": codigo, "estado": estado[:30] if estado else None, "saldo_gestion": saldo})
    return _sin_repetir(filas, ("codigo_indec",), anomalias), anomalias


# ── FOMMEP ────────────────────────────────────────────────────────────────────────

_FOMMEP_CANTIDADES = {
    "CANT_MOVILES": "cant_moviles",
    "CANT_EDIFICIOS_A": "cant_edificios_a",
    "CANT_EDIFICIOS_B": "cant_edificios_b",
    "CANT_EDIFICIOS_C": "cant_edificios_c",
    "CANT_EDIFICIOS_TOTAL": "cant_edificios_total",
}
_FOMMEP_MONTOS = {
    "MONTO_MOVILES": "monto_moviles",
    "MONTO_EDIFICIOS_A": "monto_edificios_a",
    "MONTO_EDIFICIOS_B": "monto_edificios_b",
    "MONTO_EDIFICIOS_C": "monto_edificios_c",
    "MONTO_EDIFICIOS_TOTAL": "monto_edificios_total",
    "MONTO_TOTAL": "monto_total",
}


def parsear_fommep(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Encabezados(valores, ("ID_LOC", "AÑO", *_FOMMEP_CANTIDADES, *_FOMMEP_MONTOS))
    filas: list[dict] = []
    anomalias: list[dict] = []
    for n, fila in _filas(valores):
        codigo = _codigo(enc, fila, n, anomalias)
        if codigo is None:
            continue
        anio, _ = entero(enc.get(fila, "AÑO"))
        if not anio:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        cantidades = {}
        for encabezado, campo in _FOMMEP_CANTIDADES.items():
            valor, invalido = entero(enc.get(fila, encabezado))
            cantidades[campo] = valor
            if invalido:
                anomalias.append({"tipo": "valor_invalido", "codigo": codigo, "columna": encabezado})
        filas.append({
            "codigo_indec": codigo, "anio": anio, **cantidades,
            **_montos(enc, fila, _FOMMEP_MONTOS, codigo, anomalias),
        })
    return _sin_repetir(filas, ("codigo_indec", "anio"), anomalias), anomalias


# ── EMPLEADOS (restringido) ───────────────────────────────────────────────────────


def parsear_empleados(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """`NA` es "sin dato" y no se informa. Las anomalías nunca llevan valores (spec §6)."""
    enc = _Encabezados(valores, ("ID_LOC", "AÑO", "EMPLEADOS", "SALARIO PROMEDIO", "MASA SALARIAL"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    for n, fila in _filas(valores):
        codigo = _codigo(enc, fila, n, anomalias)
        if codigo is None:
            continue
        anio, _ = entero(enc.get(fila, "AÑO"))
        if not anio:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        empleados, inv_e = entero(enc.get(fila, "EMPLEADOS"))
        salario, inv_s = monto(enc.get(fila, "SALARIO PROMEDIO"))
        masa, inv_m = monto(enc.get(fila, "MASA SALARIAL"))
        for invalido, campo in ((inv_e, "empleados"), (inv_s, "salario_promedio"), (inv_m, "masa_salarial")):
            if invalido:
                anomalias.append({"tipo": "valor_invalido", "codigo": codigo, "campo": campo})
        filas.append({
            "codigo_indec": codigo, "anio": anio,
            "empleados": empleados, "salario_promedio": salario, "masa_salarial": masa,
        })
    return _sin_repetir(filas, ("codigo_indec", "anio"), anomalias), anomalias
