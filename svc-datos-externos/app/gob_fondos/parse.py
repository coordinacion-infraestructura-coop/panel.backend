"""Parseo puro (sin base) de las planillas de fondos de Gobierno
(spec-datos-externos-fase3-fondos.md §1 y §3).

Mismo contrato que `app/gob_transferencias/parse.py`: cada `parsear_*` recibe los valores
crudos de una pestaña (`UNFORMATTED_VALUE`) y devuelve `(filas, anomalias)`; columnas por
encabezado, `EstructuraInvalida` si falta una obligatoria, anomalías sin valores.

Las columnas de personas (`INTENDENTE`, `CUIT`, `OBSERVACIONES`) llegan vacías: el sync no
las pide (spec §3). Ningún parser las usa.
"""
import re
import unicodedata
from datetime import date
from typing import Any

from app.gob_transferencias.parse import (
    _MESES,
    EstructuraInvalida,
    _Encabezados,
    _filas,
    _limpio,
    entero,
    fecha,
    mes_de,
    monto,
)
from app.gobierno.sync import normalizar_codigo

# Encabezados con datos de personas: el sync arma los rangos de lectura sin ellos.
COLUMNAS_SENSIBLES = ("INTENDENTE", "CUIT", "OBSERVACIONES")

_MESES_CORTOS = {nombre[:3]: n for nombre, n in _MESES.items()}

FONDO_PERMANENTE = "fondo_permanente"
FONDO_AMBIENTAL = "fondo_ambiental"
COMUNIDADES_REGIONALES = "comunidades_regionales"


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


class _Enc(_Encabezados):
    """`_Encabezados` que además encuentra el encabezado sin tildes o por prefijo: estas
    planillas escriben `RESOLUCION` y `RESOLUCIÓN` según la columna."""

    def __init__(self, valores: list[list[Any]], obligatorios: tuple[str, ...]):
        super().__init__(valores, ())
        for i, h in enumerate(self.norm):
            self.idx.setdefault(sin_tildes(h), i)
        faltantes = [h for h in obligatorios if self.buscar(h) is None]
        if faltantes:
            raise EstructuraInvalida(f"faltan encabezados: {', '.join(faltantes)}")

    def buscar(self, nombre: str) -> str | None:
        clave = sin_tildes(nombre)
        if clave in self.idx:
            return clave
        return next((h for h in self.idx if h.startswith(clave)), None)

    def get(self, fila: list[Any], nombre: str) -> Any:
        clave = self.buscar(nombre)
        return super().get(fila, clave) if clave else None


def es_sensible(encabezado: Any, excluidas: tuple[str, ...] = COLUMNAS_SENSIBLES) -> bool:
    h = sin_tildes(_limpio(encabezado).upper())
    return any(h.startswith(s) for s in excluidas)


def fecha_texto(raw: Any) -> date | None:
    """Además de lo que admite `fecha`: `30 de enero de 2025` y `28-dic-2023`."""
    f = fecha(raw)
    if f or not isinstance(raw, str):
        return f
    s = sin_tildes(_limpio(raw).lower())
    m = re.match(r"^(\d{1,2})\s+de\s+([a-z]+)\s+(?:de|del)\s+(\d{4})$", s) or re.match(r"^(\d{1,2})-([a-z]{3,})-(\d{2,4})$", s)
    if not m:
        return None
    d, nombre, a = int(m.group(1)), m.group(2), int(m.group(3))
    mes = _MESES.get(nombre) or _MESES_CORTOS.get(nombre[:3])
    if not mes:
        return None
    try:
        return date(a + 2000 if a < 100 else a, mes, d)
    except ValueError:
        return None


def etapas(raw: Any) -> tuple[int | None, int | None]:
    """`49` -> (49, 49); `49 a 50`, `49 y 50`, `48 (b) a 50` -> (48, 50); `51 (a)` -> (51, 51)."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return int(raw), int(raw)
    numeros = [int(n) for n in re.findall(r"\d+", str(raw or ""))]
    return (numeros[0], numeros[-1]) if numeros else (None, None)


def _texto(raw: Any, largo: int | None = None) -> str | None:
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    s = _limpio(raw)
    if not s:
        return None
    return s[:largo] if largo else s


def es_ente(codigo: str) -> bool:
    """Comunidades regionales (`428`–`453`): códigos de tres dígitos o menos."""
    return codigo.isdigit() and int(codigo) < 1000


def _monto(enc: _Enc, fila: list[Any], columna: str, ref: str | None, anomalias: list[dict]) -> float | None:
    valor, invalido = monto(enc.get(fila, columna))
    if invalido:
        anomalias.append({"tipo": "valor_invalido", "codigo": ref, "columna": columna})
    return valor


def _contar(anomalias: list[dict], tipo: str, cantidad: int) -> None:
    """Anomalías esperables y repetidas en cada corrida: una sola entrada con el total."""
    if cantidad:
        anomalias.append({"tipo": tipo, "cantidad": cantidad})


# ── Fondo Permanente ───────────────────────────────────────────────────────────────


def _es_control(enc: _Enc, fila: list[Any]) -> bool:
    """Filas de control de `FONDO PERM` (`ULTIMA DISPONIBLE`, `Disponible`): `ID_LOC = 0`."""
    raw = enc.get(fila, "ID_LOC")
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw == 0


def parsear_fperm_localidad(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Enc(valores, ("ID_LOC", "ULTIMA CUOTA", "MONTO", "ULT_C_SOC", "AULT_C_S"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    vistos: set[str] = set()
    for n, fila in _filas(valores):
        if _es_control(enc, fila):
            continue
        codigo = normalizar_codigo(enc.get(fila, "ID_LOC"))
        if codigo is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        if codigo in vistos:
            anomalias.append({"tipo": "fila_repetida", "codigo": codigo})
            continue
        vistos.add(codigo)
        ultima, _ = entero(enc.get(fila, "ULTIMA CUOTA"))
        filas.append({
            "codigo_indec": codigo,
            "ultima_etapa": ultima,
            "disponible": _monto(enc, fila, "MONTO", codigo, anomalias),
            "recibio_ultima": entero(enc.get(fila, "ULT_C_SOC"))[0] == 1,
            "recibio_anteultima": entero(enc.get(fila, "AULT_C_S"))[0] == 1,
        })
    return filas, anomalias


def parsear_fperm_valores(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Filas de control de `FONDO PERM`: `ULTIMA DISPONIBLE` trae la última etapa habilitada en
    `ULTIMA CUOTA`; `Disponible`, el saldo en cuenta en `MONTO`."""
    enc = _Enc(valores, ("ID_LOC", "LOCALIDAD", "ULTIMA CUOTA", "MONTO"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    for _n, fila in _filas(valores):
        if not _es_control(enc, fila):
            continue
        etiqueta = sin_tildes(_limpio(enc.get(fila, "LOCALIDAD")).upper())
        if etiqueta.startswith("ULTIMA"):
            valor, _ = monto(enc.get(fila, "ULTIMA CUOTA"))
            concepto = "ultima_etapa_habilitada"
        elif etiqueta.startswith("DISPONIBLE"):
            valor, _ = monto(enc.get(fila, "MONTO"))
            concepto = "saldo_cuenta"
        else:
            continue
        if valor is not None:
            filas.append({"fondo": FONDO_PERMANENTE, "concepto": concepto, "anio": None, "monto": valor})
    for concepto in ("ultima_etapa_habilitada", "saldo_cuenta"):
        if not any(f["concepto"] == concepto for f in filas):
            anomalias.append({"tipo": "valor_de_control_faltante", "concepto": concepto})
    return filas, anomalias


def parsear_fperm_etapas(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Las filas repetidas idénticas se guardan una vez sin descartar nada (spec §1.1); una
    repetida con otro monto sí es un descarte."""
    enc = _Enc(valores, ("ID_LOC", "CUOTA", "MONTO"))
    filas: dict[tuple[str, int], dict] = {}
    anomalias: list[dict] = []
    identicas = 0
    for n, fila in _filas(valores):
        codigo = normalizar_codigo(enc.get(fila, "ID_LOC"))
        if codigo is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        etapa, _ = entero(enc.get(fila, "CUOTA"))
        if not etapa:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        valor = _monto(enc, fila, "MONTO", codigo, anomalias)
        previa = filas.get((codigo, etapa))
        if previa is not None:
            if previa["monto"] == valor:
                identicas += 1
            else:
                anomalias.append({"tipo": "fila_repetida", "codigo": codigo})
            continue
        filas[(codigo, etapa)] = {"codigo_indec": codigo, "etapa": etapa, "monto": valor}
    _contar(anomalias, "filas_identicas_unificadas", identicas)
    return list(filas.values()), anomalias


def parsear_fperm_prestamos(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Las filas sin `ID_LOC` se guardan con código nulo: suman al total provincial."""
    enc = _Enc(valores, ("ID_LOC", "ETAPAS", "FECHA", "MONTO TOTAL", "CUOTA", "PLAZO"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    sin_codigo = 0
    for n, fila in _filas(valores):
        codigo = normalizar_codigo(enc.get(fila, "ID_LOC"))
        total = _monto(enc, fila, "MONTO TOTAL", codigo, anomalias)
        if total is None:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        if codigo is None:
            sin_codigo += 1
        raw_etapas = enc.get(fila, "ETAPAS")
        desde, hasta = etapas(raw_etapas)
        raw_mes = enc.get(fila, "COPA DESC.")
        mes = mes_de(raw_mes)
        if mes is None and _limpio(raw_mes):
            anomalias.append({"tipo": "valor_invalido", "codigo": codigo, "columna": "COPA DESC."})
        plazo, _ = entero(enc.get(fila, "PLAZO"))
        filas.append({
            "codigo_indec": codigo,
            "etapas_texto": _texto(raw_etapas, 60),
            "etapa_desde": desde,
            "etapa_hasta": hasta,
            "fecha": fecha_texto(enc.get(fila, "FECHA")),
            "mes_inicio_descuento": mes,
            "monto_total": total,
            "cuota": _monto(enc, fila, "CUOTA", codigo, anomalias),
            "plazo": plazo,
            "ord_res": _texto(enc.get(fila, "ORD./RES."), 60),
            "sticker": _texto(enc.get(fila, "STICKER"), 120),
            "fecha_ingreso": fecha_texto(enc.get(fila, "FECHA INGRESO")),
            "destino": _texto(enc.get(fila, "DESTINO DEL PRESTAMO")),
        })
    _contar(anomalias, "prestamos_sin_codigo", sin_codigo)
    return filas, anomalias


# ── Fondo Ambiental ────────────────────────────────────────────────────────────────


def parsear_fondo_ambiental(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    enc = _Enc(valores, ("ID_LOC", "AÑO", "OBJETO", "MONTO", "ESTADO"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    for n, fila in _filas(valores):
        codigo = normalizar_codigo(enc.get(fila, "ID_LOC"))
        if codigo is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        valor = _monto(enc, fila, "MONTO", codigo, anomalias)
        if valor is None:
            anomalias.append({"tipo": "fila_invalida", "codigo": codigo, "fila": n})
            continue
        anio, _ = entero(enc.get(fila, "AÑO"))
        ente = es_ente(codigo)
        filas.append({
            "codigo_indec": None if ente else codigo,
            "codigo_ente": codigo if ente else None,
            "nombre_ente": _texto(enc.get(fila, "LOCALIDAD"), 150) if ente else None,
            "departamento_ente": _texto(enc.get(fila, "DEPARTAMENTO"), 100) if ente else None,
            "anio": anio,
            "expediente": _texto(enc.get(fila, "N° EXPEDIENTE"), 60),
            "convenio": _texto(enc.get(fila, "N° DE CONVENIO"), 60),
            "fecha_convenio": fecha_texto(enc.get(fila, "FECHA DE CONVENIO")),
            "resolucion": _texto(enc.get(fila, "N° DE RESOLUCION"), 60),
            "fecha_resolucion": fecha_texto(enc.get(fila, "FECHA DE RESOLUCION")),
            "objeto": _texto(enc.get(fila, "OBJETO")),
            "monto": valor,
            "estado": (_texto(enc.get(fila, "ESTADO"), 40) or "").upper() or None,
            "fecha_estado": fecha_texto(enc.get(fila, "FECHA ESTADO")),
        })
    return filas, anomalias


def parsear_fondo_ambiental_ingresos(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """`INGRESOS`: una celda por año, en alguna fila de ese año (spec §1.2 y §8.4)."""
    enc = _Enc(valores, ("AÑO", "INGRESOS"))
    por_anio: dict[int, float] = {}
    anomalias: list[dict] = []
    for _n, fila in _filas(valores):
        valor, _ = monto(enc.get(fila, "INGRESOS"))
        anio, _ = entero(enc.get(fila, "AÑO"))
        if valor is None:
            continue
        if not anio:
            anomalias.append({"tipo": "ingreso_sin_anio"})
            continue
        por_anio[anio] = por_anio.get(anio, 0.0) + valor
    return [{"fondo": FONDO_AMBIENTAL, "concepto": "ingresos", "anio": a, "monto": m} for a, m in sorted(por_anio.items())], anomalias


# ── Comunidades Regionales ─────────────────────────────────────────────────────────


def parsear_comunidades_regionales(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Filas de relleno (sin monto de cuota ni estado) se saltean; un destino que vino como
    número de fecha se guarda vacío (spec §1.3)."""
    enc = _Enc(valores, ("TIPO", "ID_LOC", "AÑO", "MONTO", "CUOTA", "MONTO CUOTA", "ESTADO"))
    filas: list[dict] = []
    anomalias: list[dict] = []
    relleno = destino_fecha = 0
    for n, fila in _filas(valores):
        estado = (_texto(enc.get(fila, "ESTADO"), 40) or "").upper() or None
        monto_cuota = _monto(enc, fila, "MONTO CUOTA", None, anomalias)
        total = _monto(enc, fila, "MONTO", None, anomalias)
        if estado is None and monto_cuota is None and total is None:
            relleno += 1
            continue
        codigo = normalizar_codigo(enc.get(fila, "ID_LOC"))
        if codigo is None:
            anomalias.append({"tipo": "fila_sin_codigo", "fila": n})
            continue
        raw_destino = enc.get(fila, "DESTINO")
        if isinstance(raw_destino, (int, float)) and not isinstance(raw_destino, bool):
            destino_fecha += 1
            destino = None
        else:
            destino = _texto(raw_destino)
        anio, _ = entero(enc.get(fila, "AÑO"))
        cuota, _ = entero(enc.get(fila, "CUOTA"))
        filas.append({
            "codigo_ente": codigo,
            "tipo": _texto(enc.get(fila, "TIPO"), 30),
            "anio": anio,
            "expediente": _texto(enc.get(fila, "N° EXPEDIENTE"), 60),
            "destino": destino,
            "monto": total,
            "cuota": cuota,
            "monto_cuota": monto_cuota,
            "estado": estado,
            "fecha_pago": fecha_texto(enc.get(fila, "FECHA PAGO CUOTA")),
            "resolucion": _texto(enc.get(fila, "N° RESOLUCION"), 60),
            "fecha_rendicion": fecha_texto(enc.get(fila, "FECHA RENDICION CUOTA")),
        })
    _contar(anomalias, "filas_de_relleno", relleno)
    _contar(anomalias, "destino_con_fecha", destino_fecha)
    return filas, anomalias


def parsear_comunidades_regionales_credito(valores: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Pestaña `Control`: crédito vigente por año, de funcionamiento y de obras. Las columnas
    de saldo son fórmulas de la planilla; el saldo se recalcula en el backend."""
    enc = _Enc(valores, ("AÑO", "FUNCIONAMIENTO", "OBRAS"))
    filas: list[dict] = []
    for _n, fila in _filas(valores):
        anio, _ = entero(enc.get(fila, "AÑO"))
        if not anio:
            continue
        for columna, concepto in (("FUNCIONAMIENTO", "credito_funcionamiento"), ("OBRAS", "credito_obras")):
            valor, _ = monto(enc.get(fila, columna))
            filas.append({"fondo": COMUNIDADES_REGIONALES, "concepto": concepto, "anio": anio, "monto": valor or 0.0})
    return filas, []
