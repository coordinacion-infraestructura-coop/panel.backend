import asyncio
import threading
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


# ── Escritura (ADR-034) ─────────────────────────────────────────────────────────
# Cliente aparte, con scope de escritura, para no ampliar el de lectura. Uno por hilo:
# googleapiclient/httplib2 no se puede compartir entre hilos (spec-tablero-gobierno-
# actualizar.md 1.0.2) y `asyncio.to_thread` puede usar hilos distintos en cada llamada.
SHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

_write_local = threading.local()


def _get_write_service():
    service = getattr(_write_local, "service", None)
    if service is None:
        credentials, _ = google.auth.default(scopes=[SHEETS_WRITE_SCOPE])
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        _write_local.service = service
    return service


def _update_and_clear_sync(
    spreadsheet_id: str, updates: list[tuple[str, list[list[Any]]]], clear_range: str
) -> None:
    values = _get_write_service().spreadsheets().values()
    if updates:
        values.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": [{"range": rng, "values": vals} for rng, vals in updates],
            },
        ).execute()
    values.clear(spreadsheetId=spreadsheet_id, range=clear_range, body={}).execute()


async def update_and_clear(
    spreadsheet_id: str, updates: list[tuple[str, list[list[Any]]]], clear_range: str
) -> None:
    """Escribe cada `(rango, valores)` de `updates` y después borra `clear_range`.

    Primero escribe y después borra el sobrante: si la llamada falla a mitad de camino,
    la planilla queda con datos (viejos o nuevos), nunca vacía.

    `USER_ENTERED`: Sheets interpreta las fechas ISO como fecha y los números como
    número, igual que si se tipearan a mano. Requiere que la planilla esté compartida
    como Editor con la Service Account de runtime.
    """
    await asyncio.to_thread(_update_and_clear_sync, spreadsheet_id, updates, clear_range)
