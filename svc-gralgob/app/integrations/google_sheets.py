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
    """
    service = getattr(_local, "service", None)
    if service is None:
        credentials, _ = google.auth.default(scopes=[SHEETS_READONLY_SCOPE])
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        _local.service = service
    return service


def _get_values_sync(spreadsheet_id: str, range_name: str, sin_formato: bool) -> list[list[Any]]:
    service = _get_service()
    extra = (
        {"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"}
        if sin_formato
        else {}
    )
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name, **extra)
        .execute()
    )
    return result.get("values", [])


async def get_values(spreadsheet_id: str, range_name: str, sin_formato: bool = False) -> list[list[Any]]:
    """Lee un rango de celdas de un Google Sheet.

    `sin_formato=True` pide valores sin formato y fechas como serial, para no depender de la
    configuración regional de la planilla (ATP Interno, spec-atp-interno.md §3).

    El cliente googleapiclient es síncrono (httplib2); se corre en un thread
    aparte para no bloquear el event loop de FastAPI.
    """
    return await asyncio.to_thread(_get_values_sync, spreadsheet_id, range_name, sin_formato)
