"""Ubicación de puntos en los polígonos de gobierno local (sin dependencias
geoespaciales). Alcanza para ~7.000 puntos contra 427 polígonos simplificados.

Los anillos vienen del ArcGIS de Estadística (formato Esri: exteriores e
interiores mezclados); la regla par-impar sobre todos los anillos resuelve los
agujeros sin distinguirlos.
"""
from typing import Any


def _dentro(x: float, y: float, anillos: list[list[list[float]]]) -> bool:
    adentro = False
    for anillo in anillos:
        n = len(anillo)
        for i in range(n):
            x0, y0 = anillo[i]
            x1, y1 = anillo[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
                adentro = not adentro
    return adentro


class IndicePoligonos:
    def __init__(self, poligonos: dict[str, list[list[list[float]]]]):
        self._items: list[tuple[str, tuple[float, float, float, float], Any]] = []
        for codigo, anillos in poligonos.items():
            puntos = [p for anillo in anillos for p in anillo]
            if not puntos:
                continue
            xs = [p[0] for p in puntos]
            ys = [p[1] for p in puntos]
            self._items.append((codigo, (min(xs), min(ys), max(xs), max(ys)), anillos))

    def __len__(self) -> int:
        return len(self._items)

    def ubicar(self, lng: float | None, lat: float | None) -> str | None:
        """Código del gobierno local que contiene el punto, o `None`."""
        if lng is None or lat is None:
            return None
        for codigo, (x0, y0, x1, y1), anillos in self._items:
            if x0 <= lng <= x1 and y0 <= lat <= y1 and _dentro(lng, lat, anillos):
                return codigo
        return None


def centroide(geometria: dict[str, Any] | None) -> tuple[float, float] | None:
    """Centroide del anillo exterior del polígono más grande de un GeoJSON
    (Polygon o MultiPolygon)."""
    if not geometria or not geometria.get("coordinates"):
        return None
    poligonos = geometria["coordinates"] if geometria.get("type") == "MultiPolygon" else [geometria["coordinates"]]
    mejor: tuple[float, float, float] | None = None
    for poligono in poligonos:
        anillo = [(float(p[0]), float(p[1])) for p in poligono[0]]
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(anillo, anillo[1:] + anillo[:1]):
            cruz = x0 * y1 - x1 * y0
            a += cruz
            cx += (x0 + x1) * cruz
            cy += (y0 + y1) * cruz
        if a == 0:
            continue
        if mejor is None or abs(a) > mejor[0]:
            mejor = (abs(a), cx / (3 * a), cy / (3 * a))
    return (mejor[1], mejor[2]) if mejor else None
