import asyncio
import threading
from typing import Any

import google.auth
from googleapiclient.discovery import build

SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

# Un cliente por hilo: el de googleapiclient (httplib2) no se puede compartir entre hilos, y
# las lecturas corren en `asyncio.to_thread`. Con un cliente global, dos syncs simultáneos en la
# misma instancia se rompían la conexión entre sí (502 al dispararse juntos desde el botón
# "Actualizar datos" del Tablero de Gobierno, 2026-10-22).
_local = threading.local()


def _get_service():
    """Construye (una vez por hilo) el cliente de Sheets API v4.

    Usa Application Default Credentials: en Cloud Run, la identidad de la
    Service Account de runtime del servicio; en desarrollo local, la cuenta
    autenticada vía `gcloud auth application-default login`. No requiere
    ninguna clave ni variable de entorno con credenciales — el Sheet debe
    compartirse (Viewer) con esa identidad.

    Copia de `svc-gralgob/app/integrations/google_sheets.py` con el agregado
    de `value_render_option`. El scope es de solo lectura: este servicio no
    escribe en ninguna planilla (spec-datos-externos-fase1-nomenclador-demografia.md §2).
    """
    service = getattr(_local, "service", None)
    if service is None:
        credentials, _ = google.auth.default(scopes=[SHEETS_READONLY_SCOPE])
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        _local.service = service
    return service


def _get_values_sync(spreadsheet_id: str, range_name: str, value_render_option: str) -> list[list[Any]]:
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name, valueRenderOption=value_render_option)
        .execute()
    )
    return result.get("values", [])


async def get_values(
    spreadsheet_id: str,
    range_name: str,
    value_render_option: str = "FORMATTED_VALUE",
) -> list[list[Any]]:
    """Lee un rango de celdas de un Google Sheet.

    `value_render_option="UNFORMATTED_VALUE"` devuelve los números como
    números, sin depender de la configuración regional de cada planilla (las
    de Gobierno mezclan `140.105` y `142,007` para el mismo código).

    El cliente googleapiclient es síncrono (httplib2); se corre en un thread
    aparte para no bloquear el event loop de FastAPI.
    """
    return await asyncio.to_thread(_get_values_sync, spreadsheet_id, range_name, value_render_option)


def _batch_get_sync(spreadsheet_id: str, ranges: list[str], value_render_option: str) -> list[list[list[Any]]]:
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .batchGet(spreadsheetId=spreadsheet_id, ranges=ranges, valueRenderOption=value_render_option)
        .execute()
    )
    return [r.get("values", []) for r in result.get("valueRanges", [])]


async def batch_get_values(
    spreadsheet_id: str,
    ranges: list[str],
    value_render_option: str = "FORMATTED_VALUE",
) -> list[list[list[Any]]]:
    """Varios rangos en una sola llamada, en el mismo orden. Sirve para leer una pestaña
    salteando columnas (spec-datos-externos-fase3-fondos.md §3)."""
    return await asyncio.to_thread(_batch_get_sync, spreadsheet_id, ranges, value_render_option)
