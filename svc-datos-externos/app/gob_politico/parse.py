"""Parseo puro (sin base) del padrón de intendentes y de la planilla de elecciones
(spec-datos-externos-fase6-politico.md §1 y §3).

Mismo contrato que las Fases 2 a 5: cada `parsear_*` recibe los valores crudos de una pestaña
(`UNFORMATTED_VALUE`), con el encabezado en la primera fila, y devuelve `(filas, anomalias)`.
Las anomalías nunca llevan nombres de personas, partidos por localidad ni teléfonos (spec §5).

Las columnas excluidas (`COLUMNAS_EXCLUIDAS`) llegan vacías porque el sync no las pide.
"""
import re
from typing import Any, Callable

from app.gob_fondos.parse import _Enc, _texto, sin_tildes
from app.gob_gestion.parse import _contar, catalogo, codigo_localidad, fecha_flexible
from app.gob_transferencias.parse import EstructuraInvalida, _filas, entero, es_error, monto, norm_header

# Intendente y partido salen solo del padrón: en las pestañas de la planilla 18 no se piden
# (spec §3.1). `HABITANTES` tampoco: la población es la del Censo.
COLUMNAS_EXCLUIDAS = ("INTENDENTE", "PARTIDO", "HABITANTES")

ELECCIONES = {"2025": "diputados_2025", "2023": "diputados_2023", "2021": "diputados_2021"}
OTROS = "OTROS"

# Columnas de las pestañas de circuitos que no son fuerzas.
_FIJAS_CIRCUITO = {
    "CIRCUITO_ID", "CIRCUITO_NOMBRE", "SECCION_NOMBRE", "PADRON", "MESAS", "NULOS", "BLANCOS", "COMANDO",
    "IMPUGNADOS", "TOTALVOTOS", "AFIRMATIVOS", "VALIDOS", "RECURRIDO", "RECURRIDOS",
}


def clave_circuito(raw: Any) -> str | None:
    """`12`, `12.0` -> `"12"`; `" 12a "` -> `"12A"`."""
    if raw is None or isinstance(raw, bool) or es_error(raw):
        return None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    s = str(raw).strip().upper()
    return s or None


def clave_nombre(raw: Any) -> str:
    """Nombre de localidad comparable: sin tildes, mayúsculas, sin puntos ni guiones."""
    s = sin_tildes(str(raw or "")).upper().replace(".", " ").replace("-", " ")
    return " ".join(s.split())


def si_no(raw: Any) -> tuple[bool | None, bool]:
    """`(valor, invalido)`: `SI`/`NO`; vacío -> `(None, False)`; otra cosa -> `(None, True)`."""
    s = catalogo(raw)
    if s is None:
        return None, False
    if s in ("SI", "SÍ"):
        return True, False
    if s == "NO":
        return False, False
    return None, True


def celular(raw: Any) -> str | None:
    """Solo dígitos. El valor nunca va a anomalías ni a logs."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    digitos = re.sub(r"\D", "", str(raw))
    return digitos[:30] or None


def _pct(raw: Any) -> float | None:
    valor, _ = monto(raw)
    return valor


# ── Padrón de intendentes ──────────────────────────────────────────────────────────


def parsear_intendentes(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Las 25 filas de comunidades regionales (código de texto, sin intendente) no son gobiernos
    locales: se saltean sin anomalía."""
    enc = _Enc(valores, ("ID_LOC", "INTENDENTE"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    vistos: set[str] = set()
    sin_intendente = booleano_invalido = sin_celular = repetidos = 0
    for n, fila in _filas(valores):
        codigo = codigo_localidad(enc.get(fila, "ID_LOC"))
        if codigo is None:
            continue
        if codigo in vistos:
            repetidos += 1
            continue
        vistos.add(codigo)
        reelecto, inv1 = si_no(enc.get(fila, "REELECTO"))
        continuidad, inv2 = si_no(enc.get(fila, "CONTINUIDAD"))
        booleano_invalido += inv1 + inv2
        intendente = _texto(enc.get(fila, "INTENDENTE"), 150)
        sin_intendente += intendente is None
        cel = celular(enc.get(fila, "CELULAR"))
        sin_celular += cel is None
        foto = _texto(enc.get(fila, "FOTO"), 500)
        filas.append({
            "codigo_indec": codigo,
            "intendente": intendente,
            "reelecto": reelecto,
            "partido": _texto(enc.get(fila, "PARTIDO"), 150),
            "continuidad": continuidad,
            "celular": cel,
            "foto_url": foto if foto and foto.startswith("http") else None,
        })
    _contar(anomalias, "sin_intendente", sin_intendente)
    _contar(anomalias, "si_no_invalido", booleano_invalido)
    _contar(anomalias, "sin_celular", sin_celular)
    _contar(anomalias, "fila_repetida", repetidos)
    return filas, anomalias


# ── Votos por circuito ─────────────────────────────────────────────────────────────


def parsear_circuitos(eleccion: str) -> Callable[[list[list[Any]]], tuple[list[dict], list[dict]]]:
    """Parser de una pestaña de año (`2025`, `2023`, `2021`). Todo encabezado que no es una
    columna fija es una fuerza; se quita el prefijo `POSITIVO_`."""

    def parsear(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
        enc = _Enc(valores, ("CIRCUITO_ID", "AFIRMATIVOS"))
        fuerzas = []
        for i, h in enumerate(enc.norm):
            h = sin_tildes(h)
            if h and h not in _FIJAS_CIRCUITO:
                fuerzas.append((i, h.removeprefix("POSITIVO_").strip()))
        if not fuerzas:
            raise EstructuraInvalida("la pestaña no tiene columnas de fuerzas")
        filas: list[dict] = []
        anomalias: list[dict] = []
        vistos: set[str] = set()
        invalidos = 0
        for n, fila in _filas(valores):
            cid = clave_circuito(enc.get(fila, "CIRCUITO_ID"))
            if cid is None:
                anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
                continue
            if cid in vistos:
                anomalias.append({"tipo": "fila_repetida", "fila": n})
                continue
            vistos.add(cid)

            def num(col: str) -> int | None:
                nonlocal invalidos
                v, inv = entero(enc.get(fila, col))
                invalidos += inv
                return v

            votos = {}
            for i, f in fuerzas:
                v, inv = entero(fila[i] if i < len(fila) else None)
                invalidos += inv
                votos[f] = v or 0
            filas.append({
                "eleccion": eleccion,
                "circuito_id": cid,
                "circuito_nombre": _texto(enc.get(fila, "CIRCUITO_NOMBRE"), 150),
                "departamento": _texto(enc.get(fila, "SECCION_NOMBRE"), 100),
                "padron": num("PADRON"),
                "mesas": num("MESAS"),
                "nulos": num("NULOS"),
                "blancos": num("BLANCOS"),
                "impugnados": num("IMPUGNADOS"),
                "recurridos": num("RECURRIDOS") if enc.buscar("RECURRIDOS") else num("RECURRIDO"),
                "total_votos": num("TOTALVOTOS"),
                "afirmativos": num("AFIRMATIVOS"),
                "validos": num("VALIDOS"),
                "votos": votos,
            })
        _contar(anomalias, "numero_invalido", invalidos)
        return filas, anomalias

    return parsear


def parsear_circuito_localidad(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """`RESUMEN_VOTOS_CIRCUITOS`: solo `LOCALIDAD` y `circuito_id`. El código INDEC lo completa
    el sync contra el nomenclador. Los circuitos rurales sin gobierno local (parajes) vienen sin
    localidad a propósito: no son un error, cuentan en la provincia y en su departamento."""
    enc = _Enc(valores, ("LOCALIDAD", "CIRCUITO_ID"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    vistos: set[str] = set()
    sin_gobierno_local = 0
    for n, fila in _filas(valores):
        cid = clave_circuito(enc.get(fila, "CIRCUITO_ID"))
        localidad = _texto(enc.get(fila, "LOCALIDAD"), 150)
        if cid is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        if localidad is None:
            sin_gobierno_local += 1
            continue
        if cid in vistos:
            anomalias.append({"tipo": "fila_repetida", "fila": n})
            continue
        vistos.add(cid)
        filas.append({"circuito_id": cid, "localidad": localidad, "codigo_indec": None})
    _contar(anomalias, "circuito_sin_gobierno_local", sin_gobierno_local)
    return filas, anomalias


# ── Municipales 2023 ───────────────────────────────────────────────────────────────


def parsear_municipales(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Las filas sin votos (texto en las columnas numéricas) se guardan con votos nulos."""
    enc = _Enc(valores, ("ID_LOC", "PARTIDO_POLITICO_GANADOR", "NOMBRE_GOBERNANTE"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    vistos: set[str] = set()
    sin_votos = participacion_alta = 0

    def num(fila: list[Any], col: str) -> int | None:
        v = enc.get(fila, col)
        return entero(v)[0] if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def pct(fila: list[Any], col: str) -> float | None:
        v = enc.get(fila, col)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    for n, fila in _filas(valores):
        codigo = codigo_localidad(enc.get(fila, "ID_LOC"))
        if codigo is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        if codigo in vistos:
            anomalias.append({"tipo": "fila_repetida", "fila": n})
            continue
        vistos.add(codigo)
        afirmativos = num(fila, "TOTAL VOTOS AFIRMATIVOS")
        sin_votos += afirmativos is None
        participacion = pct(fila, "PARTICIP ELECT")
        participacion_alta += participacion is not None and participacion > 1
        filas.append({
            "codigo_indec": codigo,
            "periodo": _texto(enc.get(fila, "PERIODO"), 20),
            "tipo_gobierno": catalogo(enc.get(fila, "TIPO_GOB"), 40),
            "fecha": fecha_flexible(enc.get(fila, "FECHA_ELEC")),
            "participacion": participacion,
            "afirmativos": afirmativos,
            "padron": num(fila, "TOTAL PADRON"),
            "ganador_partido": _texto(enc.get(fila, "PARTIDO_POLITICO_GANADOR"), 200),
            "ganador_partido_norm": catalogo(enc.get(fila, "PARTIDO_POLITICO_GANADOR_NORM"), 100),
            "ganador_votos": num(fila, "VOTOS_POSIT_GANADOR"),
            "ganador_pct": pct(fila, "%_GANADOR"),
            "ganador_nombre": _texto(enc.get(fila, "NOMBRE_GOBERNANTE"), 150),
            "ganador_sexo": catalogo(enc.get(fila, "SEXO"), 10),
            "segundo_partido": _texto(enc.get(fila, "PARTIDO_POLITICO_2DO"), 200),
            "segundo_partido_norm": catalogo(enc.get(fila, "PARTIDO_POLITICO_2DO_NORM"), 100),
            "segundo_votos": num(fila, "VOTOS_POSIT_2DO"),
            "segundo_pct": pct(fila, "%_SEGUNDO"),
            "segundo_nombre": _texto(enc.get(fila, "NOMBRE_SEGUNDO"), 150),
            "otras_votos": num(fila, "VOTOS_OTRAS_FUERZAS"),
            "otras_pct": pct(fila, "%_OTRAS"),
        })
    _contar(anomalias, "municipal_sin_votos", sin_votos)
    _contar(anomalias, "participacion_mayor_a_100", participacion_alta)
    return filas, anomalias


# ── Pestañas pegadas (copia y control) ─────────────────────────────────────────────

# Por pestaña: posición de la columna de localidad y (posición, ruta en `datos`, fragmento que
# tiene que estar en el encabezado). La posición fija es a propósito: estas pestañas repiten
# encabezados (`LLA`, `Afirmativos`) y el año está en la fila de arriba.
_D25 = [(6, "d25.LLA", "LLA"), (7, "d25.PU", "PU"), (8, "d25.DC", "DC"), (9, "d25.OTROS", "OTROS")]
COPIAS: dict[str, tuple[int, list[tuple[int, str, str]]]] = {
    "RESULTADOS CALVO": (0, [
        (5, "padron", "PADRON"), *_D25,
        (10, "ganador_25", "GANADOR"), (11, "segundo_25", "SEGUNDO"),
        (12, "dif_ganador_segundo_25", "DIFERENCIA GANADOR"), (13, "dif_lla_pu_25", "DIFERENCIA LLA"),
        (14, "gob23.HxC", "(HXC)"), (15, "gob23.JxC", "(JXC)"), (16, "gob23.LLA", "(LLA)"),
        (17, "gob23.FdT", "(FDT)"), (18, "gob23.OTROS", "OTROS"),
        (19, "d23.HxC", "HXC"), (20, "d23.JxC", "JXC"), (21, "d23.LLA", "LLA"), (22, "d23.OTROS", "OTROS"),
        (23, "d21.HxC", "HXC"), (24, "d21.JxC", "JXC"), (25, "d21.LLA", "LLA"), (26, "d21.OTROS", "OTROS"),
    ]),
    "GANADORES": (1, [(4, "alineacion", "ALIADO"), (6, "ganador_25", "2025"), (7, "ganador_23", "2023"), (8, "ganador_21", "2021")]),
    "RESUMEN_VOTOS": (0, [
        (4, "padron", "PADRON"),
        (5, "v25.AFIRMATIVOS", "AFIRMATIVOS"), (6, "v25.LLA", "LLA"), (7, "v25.PU", "PU"), (8, "v25.DC", "DC"), (9, "v25.OTROS", "OTROS"),
        (10, "v23.AFIRMATIVOS", "AFIRMATIVOS"), (11, "v23.HxC", "HXC"), (12, "v23.JxC", "JXC"), (13, "v23.LLA", "LLA"), (14, "v23.OTROS", "OTROS"),
        (15, "v21.AFIRMATIVOS", "AFIRMATIVOS"), (16, "v21.HxC", "HXC"), (17, "v21.JxC", "JXC"), (18, "v21.LLA", "LLA"), (19, "v21.OTROS", "OTROS"),
    ]),
}


def parsear_copia(pestana: str) -> Callable[[list[list[Any]]], tuple[list[dict], list[dict]]]:
    col_localidad, campos = COPIAS[pestana]

    def parsear(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
        if not valores:
            raise EstructuraInvalida("la pestaña está vacía")
        enc = [sin_tildes(norm_header(h)) for h in valores[0]]
        faltan = [esperado for pos, _, esperado in campos if pos >= len(enc) or esperado not in enc[pos]]
        if col_localidad >= len(enc) or "LOCALIDAD" not in enc[col_localidad]:
            faltan.append("LOCALIDAD")
        if faltan:
            raise EstructuraInvalida(f"encabezados fuera de lugar: {', '.join(faltan)}")
        filas: list[dict] = []
        anomalias: list[dict] = []
        vistos: set[str] = set()
        for n, fila in _filas(valores):
            localidad = _texto(fila[col_localidad] if col_localidad < len(fila) else None, 150)
            if localidad is None:
                anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
                continue
            if clave_nombre(localidad) in vistos:
                anomalias.append({"tipo": "fila_repetida", "fila": n})
                continue
            vistos.add(clave_nombre(localidad))
            datos: dict = {}
            for pos, ruta, _ in campos:
                raw = fila[pos] if pos < len(fila) else None
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    valor: Any = raw
                else:
                    valor = None if es_error(raw) else catalogo(raw, 60)
                destino = datos
                *grupos, hoja = ruta.split(".")
                for g in grupos:
                    destino = destino.setdefault(g, {})
                destino[hoja] = valor
            filas.append({"pestana": pestana, "localidad": localidad, "codigo_indec": None, "datos": datos})
        return filas, anomalias

    return parsear
