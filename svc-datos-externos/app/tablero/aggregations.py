"""Cálculos del Tablero de Gobierno, puros (sin base), uno por fórmula del relevamiento §3
(spec-tablero-gobierno-panel.md §3.1). El frontend no recalcula montos: dibuja lo que sale de acá.
"""
from collections.abc import Iterable
from datetime import date


def serie_mensual(filas: Iterable[tuple[date, float]], anio: int) -> list[float | None]:
    """Suma por mes del año. Un mes sin ninguna fila queda en None (sin dato), no en 0:
    el tablero distingue "todavía no se publicó" de "se transfirió cero"."""
    meses: list[float | None] = [None] * 12
    for periodo, monto in filas:
        if periodo.year == anio:
            i = periodo.month - 1
            meses[i] = (meses[i] or 0.0) + float(monto)
    return meses


def ultimo_mes_con_dato(serie: list[float | None]) -> int | None:
    """Índice (0-11) del último mes con dato, o None si el año no tiene ninguno."""
    for i in range(11, -1, -1):
        if serie[i] is not None:
            return i
    return None


def acumulado(serie: list[float | None], hasta: int | None) -> float:
    """Suma de enero al mes `hasta` inclusive (ignora meses sin dato)."""
    if hasta is None:
        return 0.0
    return sum(v for v in serie[: hasta + 1] if v is not None)


def variacion(actual: float, anterior: float | None) -> float | None:
    """Variación relativa (0.25 = +25 %). None si no hay base de comparación."""
    if not anterior:
        return None
    return actual / anterior - 1


def por_habitante(monto: float, poblacion: int | None) -> float | None:
    if not poblacion:
        return None
    return monto / poblacion
