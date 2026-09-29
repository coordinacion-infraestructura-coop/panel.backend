"""Descubrimiento y descarga de los PDF mensuales de
transparencia.cba.gov.ar. El sitio bloquea clientes sin user-agent de
navegador (confirmado en el prototipo: un fetch sin ese header devuelve 403).
Los nombres de archivo no son regulares (sufijos "-1"/"-v1"/"-v2") — los
links se extraen de la página, nunca se construyen a partir del período.
"""
import re

import httpx

from app.config import settings

_LINK_RE = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)


class DescubrimientoError(Exception):
    """La página no pudo leerse o no se encontró ningún link de PDF para el
    período pedido — la corrida debe loguear la anomalía y sugerir carga
    manual, nunca inventar una URL."""


async def descubrir_links(tipo: str, periodo_label: str) -> list[str]:
    """`tipo`: "municipio" | "comuna". `periodo_label`: fragmento tal como
    aparece en el nombre del archivo (ej. "Julio-2026"), usado solo para
    filtrar los links de la página, no para construir la URL."""
    prefijo = "Recaudacion-Municipios" if tipo == "municipio" else "Recaudacion-Comunas"
    headers = {"User-Agent": settings.transferencias_user_agent}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(settings.transferencias_base_url, headers=headers)
    if resp.status_code != 200:
        raise DescubrimientoError(f"GET {settings.transferencias_base_url} devolvió {resp.status_code}")

    links = _LINK_RE.findall(resp.text)
    candidatos = [
        link for link in links
        if prefijo.lower() in link.lower() and periodo_label.lower() in link.lower()
    ]
    if not candidatos:
        raise DescubrimientoError(
            f"No se encontró ningún link de {prefijo}-*{periodo_label}*.pdf en la página."
        )
    return candidatos


async def descargar_pdf(url: str) -> bytes:
    headers = {"User-Agent": settings.transferencias_user_agent}
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    return resp.content
