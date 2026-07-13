import asyncio
from typing import Any

import google.auth
from googleapiclient.discovery import build

SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

_service = None


def _get_service():
    """Construye (una sola vez por proceso) el cliente de Sheets API v4.

    Usa Application Default Credentials: en Cloud Run, la identidad de la
    Service Account de runtime del servicio. No requiere ninguna clave ni
    variable de entorno con credenciales — el Sheet debe compartirse con
    el email de esa Service Account.
    """
    global _service
    if _service is None:
        credentials, _ = google.auth.default(scopes=[SHEETS_READONLY_SCOPE])
        _service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    return _service


def _get_values_sync(spreadsheet_id: str, range_name: str) -> list[list[Any]]:
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    return result.get("values", [])


async def get_values(spreadsheet_id: str, range_name: str) -> list[list[Any]]:
    """Lee un rango de celdas de un Google Sheet.

    El cliente googleapiclient es síncrono (httplib2); se corre en un thread
    aparte para no bloquear el event loop de FastAPI.
    """
    return await asyncio.to_thread(_get_values_sync, spreadsheet_id, range_name)
