"""Lectura mínima de Google Sheets (API v4, `values:batchGet`) con ADC de la cuenta de servicio
de Cloud Run: sin claves ni Secret Manager; la planilla se comparte como Lector con
`svc-privada@`. Mismo criterio que `app/integrations/google_sheets.py` de svc-vivienda, pero por
REST con httpx (ya es dependencia) en vez de googleapiclient. Credenciales nuevas en cada
corrida (ver los Broken pipe de clientes reusados, 2026-11-20).
"""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
_URL = "https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values:batchGet"


class SheetReadError(Exception):
    """No se pudo leer la planilla entera (permiso, red, rango): el sync responde 502."""


def _token() -> str:
    import google.auth
    from google.auth.transport.requests import Request

    creds, _ = google.auth.default(scopes=[SCOPE])
    creds.refresh(Request())
    return creds.token


async def leer_rangos(sheet_id: str, rangos: list[str]) -> dict[str, list[list]]:
    """Devuelve `{rango pedido: filas}`. Fechas como número de serie (`SERIAL_NUMBER`), el resto
    sin formato. Reintenta 3 veces ante errores de red o 5xx."""
    try:
        token = await asyncio.to_thread(_token)
    except Exception as exc:  # noqa: BLE001
        raise SheetReadError(f"Sin credenciales para Sheets: {exc}") from exc
    params = [("ranges", r) for r in rangos] + [
        ("valueRenderOption", "UNFORMATTED_VALUE"),
        ("dateTimeRenderOption", "SERIAL_NUMBER"),
    ]
    ultimo: Exception | None = None
    for intento in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    _URL.format(sheet_id=sheet_id), params=params, headers={"Authorization": f"Bearer {token}"}
                )
            if resp.status_code >= 500:
                ultimo = SheetReadError(f"Sheets respondió {resp.status_code}")
                await asyncio.sleep(2 * (intento + 1))
                continue
            if resp.status_code != 200:
                raise SheetReadError(
                    f"Sheets respondió {resp.status_code}: ¿la planilla está compartida con la cuenta de servicio?"
                )
            rangos_out = resp.json().get("valueRanges", [])
            return {r: (vr.get("values") or []) for r, vr in zip(rangos, rangos_out)}
        except httpx.HTTPError as exc:
            ultimo = exc
            await asyncio.sleep(2 * (intento + 1))
    raise SheetReadError(f"No se pudo leer la planilla: {ultimo}")
