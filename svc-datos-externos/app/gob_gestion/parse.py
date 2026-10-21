"""Parseo puro (sin base) de las planillas de gestión territorial de Gobierno
(spec-datos-externos-fase5-gestion-territorial.md §1 y §3).

Mismo contrato que las Fases 2 y 3: cada `parsear_*` recibe los valores crudos de una pestaña
(`UNFORMATTED_VALUE`) y devuelve `(filas, anomalias)`; columnas por encabezado,
`EstructuraInvalida` si falta una obligatoria, anomalías sin valores de texto.

Las columnas excluidas (`COLUMNAS_EXCLUIDAS`) llegan vacías porque el sync no las pide.
Ningún parser las usa.
"""
import re
from datetime import date
from typing import Any, Callable

from app.gob_fondos.parse import _MESES_CORTOS, _Enc, _texto, fecha_texto, sin_tildes
from app.gob_transferencias.parse import _MESES, _filas, _limpio, entero, es_error, monto
from app.gobierno.sync import normalizar_codigo

# Por pestaña: encabezados (sin tildes, prefijo) que el sync nunca pide a Sheets (spec §5).
COLUMNAS_EXCLUIDAS: dict[str, tuple[str, ...]] = {
    "Recorrido": ("TEMA", "INSTITUCION"),
    "Visitas Gober": ("INTENDENTE", "PARTIDO"),
    "Reuniones": ("DETALLE",),
}

ORIGEN_FUNCIONARIOS = "funcionarios"
ORIGEN_MINISTRO = "ministro"

SIN_DATO = "SIN DATO"
# Columnas de `Convenios` que no son convenios.
_NO_CONVENIOS = {"ID_LOC", "LOCALIDAD", "DEPARTAMENTO", "FECHA", "ANO RADIO"}


def _contar(anomalias: list[dict], tipo: str, cantidad: int) -> None:
    if cantidad:
        anomalias.append({"tipo": tipo, "cantidad": cantidad})


def codigo_localidad(raw: Any) -> str | None:
    """Código INDEC de gobierno local (6 dígitos); cualquier otra cosa -> None."""
    c = normalizar_codigo(raw)
    return c if c and c.isdigit() and len(c) == 6 else None


def codigo_zona_rural(raw: Any) -> str | None:
    c = normalizar_codigo(raw)
    return c if c and c.endswith("ZR") else None


def fecha_flexible(raw: Any) -> date | None:
    """Serial, `d/m/aaaa`, `30 de enero de 2025`, `28-dic-2023`, `1 oct 2026` o `2026-04-07`."""
    if es_error(raw):
        return None
    f = fecha_texto(raw)
    if f or not isinstance(raw, str):
        return f
    s = sin_tildes(_limpio(raw).lower())
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        a, mes, d = (int(x) for x in m.groups())
    else:
        m = re.match(r"^(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})$", s)
        if not m:
            return None
        d, a = int(m.group(1)), int(m.group(3))
        mes = _MESES.get(m.group(2)) or _MESES_CORTOS.get(m.group(2)[:3])
        if not mes:
            return None
    try:
        return date(a, mes, d)
    except ValueError:
        return None


def catalogo(raw: Any, largo: int = 80) -> str | None:
    """Valor de catálogo normalizado: mayúsculas, espacios duros y dobles colapsados."""
    if raw is None or es_error(raw):
        return None
    s = re.sub(r"\s+", " ", str(raw).replace("\xa0", " ")).strip().upper()
    return s[:largo] or None


# ── Obras ──────────────────────────────────────────────────────────────────────────


def parsear_obras(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Enc(valores, ("ID_OBRA", "ID_LOC", "TIPO", "ESTADO DE OBRA"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    estado_sin_dato = division_invalida = 0
    for n, fila in _filas(valores):
        id_obra = _texto(enc.get(fila, "ID_OBRA"), 40)
        tipo, estado = enc.get(fila, "TIPO"), enc.get(fila, "ESTADO DE OBRA")
        if not id_obra or es_error(tipo) or es_error(estado):
            anomalias.append({"tipo": "fila_invalida", "fila": n, "obra": id_obra})
            continue
        raw_loc = enc.get(fila, "ID_LOC")
        ambito = catalogo(tipo, 40)
        codigo = codigo_localidad(raw_loc)
        zona = codigo_zona_rural(raw_loc)
        provincial = catalogo(raw_loc) == "PROVINCIAL" or ambito == "PROVINCIAL"
        if not (codigo or zona or provincial):
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n, "obra": id_obra})
            continue
        est = catalogo(estado, 60)
        if est in (None, "0", "-"):
            est = SIN_DATO
            estado_sin_dato += 1
        division = enc.get(fila, "DIVISIÓN")
        if isinstance(division, (int, float)) and not isinstance(division, bool):
            division = None
            division_invalida += 1
        avance, _ = monto(enc.get(fila, "AVANCE"))
        if avance is not None and avance > 1:
            avance = avance / 100  # cargado en porcentaje
        valor, _ = monto(enc.get(fila, "MONTO"))
        filas.append({
            "id_obra": id_obra,
            "codigo_indec": None if provincial else codigo,
            "codigo_zona_rural": None if provincial else zona,
            "ambito": "PROVINCIAL" if provincial else ambito,
            "localidad": None if provincial else _texto(enc.get(fila, "LOCALIDAD"), 150),
            "departamento": None if provincial else _texto(enc.get(fila, "DEPARTAMENTO"), 100),
            "nombre": _texto(enc.get(fila, "NOMBRE DE OBRA")),
            "division": catalogo(division, 60),
            "estado": est,
            "categoria": catalogo(enc.get(fila, "CATEGORIA"), 60),
            "avance": avance,
            "fecha_inicio": fecha_flexible(enc.get(fila, "FECHA INICIO")),
            "fecha_fin": fecha_flexible(enc.get(fila, "FECHA DE FIN DE OBRA")),
            "monto": valor,
        })
    _contar(anomalias, "estado_sin_dato", estado_sin_dato)
    _contar(anomalias, "division_invalida", division_invalida)
    return filas, anomalias


# ── Visitas ────────────────────────────────────────────────────────────────────────


def parsear_recorrido(origen: str, hoy: Callable[[], date] = date.today) -> Callable[[list[list[Any]]], tuple[list[dict], list[dict]]]:
    """Parser de `Recorrido` para una de las dos planillas. Las fechas futuras o inválidas y las
    filas sin localidad son errores de carga (paraguas §3.8): se descartan."""

    def parsear(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
        enc = _Enc(valores, ("FUNCIONARIO", "FECHA", "ID_LOC", "TIPO DE VISITA"))
        limite = hoy()
        filas: list[dict] = []
        anomalias: list[dict] = []
        vistas: set[tuple] = set()
        repetidas = 0
        for n, fila in _filas(valores):
            codigo = codigo_localidad(enc.get(fila, "ID_LOC"))
            if codigo is None:
                anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
                continue
            f = fecha_flexible(enc.get(fila, "FECHA"))
            if f is None or f > limite:
                anomalias.append({"tipo": "fila_invalida", "fila": n, "motivo": "fecha_futura" if f else "fecha_invalida"})
                continue
            funcionario = _texto(enc.get(fila, "FUNCIONARIO"), 120)
            clave = (funcionario, f, codigo)
            repetidas += clave in vistas
            vistas.add(clave)
            filas.append({
                "origen": origen,
                "funcionario": funcionario,
                "fecha": f,
                "codigo_indec": codigo,
                "localidad": _texto(enc.get(fila, "LOCALIDAD"), 150),
                "departamento": _texto(enc.get(fila, "DEPARTAMENTO"), 100),
                "tipo": catalogo(enc.get(fila, "TIPO DE VISITA")),
            })
        _contar(anomalias, "visitas_repetidas", repetidas)
        return filas, anomalias

    return parsear


def parsear_visitas_gobernador(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Enc(valores, ("ID_LOC", "VISITAS", "FECHA__ULT"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    sin_fecha = 0
    for n, fila in _filas(valores):
        codigo = codigo_localidad(enc.get(fila, "ID_LOC"))
        if codigo is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        visitada = catalogo(enc.get(fila, "VISITAS")) == "SI"
        f = fecha_flexible(enc.get(fila, "FECHA__ULT"))
        sin_fecha += visitada and f is None
        filas.append({
            "codigo_indec": codigo,
            "visitada": visitada,
            "fecha_ultima": f,
            "rango_habitantes": _texto(enc.get(fila, "HABITANTES"), 40),
        })
    _contar(anomalias, "visitada_sin_fecha", sin_fecha)
    return filas, anomalias


# ── Reuniones ──────────────────────────────────────────────────────────────────────


def temas(raw: Any) -> list[str]:
    vistos: list[str] = []
    for t in re.split(r"[,;/]", str(raw or "")):
        t = catalogo(t, 60)
        if t and t not in vistos:
            vistos.append(t)
    return vistos


def parsear_reuniones(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Enc(valores, ("ID_LOC", "FECHA", "TEMAS"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    ids: set[int] = set()
    repetidos = 0
    for n, fila in _filas(valores):
        raw_loc = enc.get(fila, "ID_LOC")
        codigo, zona = codigo_localidad(raw_loc), codigo_zona_rural(raw_loc)
        if not (codigo or zona):
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        f = fecha_flexible(enc.get(fila, "FECHA"))
        if f is None:
            anomalias.append({"tipo": "fila_invalida", "fila": n, "motivo": "fecha_invalida"})
            continue
        id_reu, _ = entero(enc.get(fila, "ID_REU"))
        if id_reu is not None:
            repetidos += id_reu in ids
            ids.add(id_reu)
        filas.append({
            "id_reu": id_reu,
            "codigo_indec": codigo,
            "codigo_zona_rural": zona,
            "fecha": f,
            "temas": temas(enc.get(fila, "TEMAS")),
            "resolucion": _texto(enc.get(fila, "RESOLUCIÓN"), 40),
        })
    _contar(anomalias, "id_reunion_repetido", repetidos)
    return filas, anomalias


# ── Convenios ──────────────────────────────────────────────────────────────────────


def _es_anio(s: str | None) -> bool:
    return bool(s) and bool(re.fullmatch(r"(19|20)\d\d", s))


def parsear_convenios(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Formato largo: una fila por localidad y columna de convenio. Las columnas numéricas
    (polideportivos, parques industriales) van en `cantidad`; `AÑO RADIO` va como detalle de
    `RADIO`."""
    enc = _Enc(valores, ("ID_LOC",))
    columnas = [(i, h) for i, h in enumerate(enc.norm) if h and sin_tildes(h) not in _NO_CONVENIOS]
    filas: list[dict] = []
    anomalias: list[dict] = []
    cantidad_alta = anio_raro = 0
    for n, fila in _filas(valores):
        codigo = codigo_localidad(enc.get(fila, "ID_LOC"))
        if codigo is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        anio_radio = _texto(enc.get(fila, "AÑO RADIO"), 40)
        anio_raro += bool(anio_radio) and not _es_anio(anio_radio)
        for i, h in columnas:
            raw = fila[i] if i < len(fila) else None
            cantidad = None
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                cantidad = int(raw)
                cantidad_alta += cantidad > 10
                valor = "SI" if cantidad > 0 else "NO"
            else:
                valor = catalogo(raw, 10)
            filas.append({
                "codigo_indec": codigo,
                "convenio": h[:60],
                "valor": valor if valor in ("SI", "NO", "NC") else None,
                "cantidad": cantidad,
                "detalle": anio_radio if h == "RADIO" else None,
            })
    _contar(anomalias, "cantidad_fuera_de_rango", cantidad_alta)
    _contar(anomalias, "anio_radio_no_es_anio", anio_raro)
    return filas, anomalias
