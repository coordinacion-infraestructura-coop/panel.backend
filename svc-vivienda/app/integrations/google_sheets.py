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
# Cliente aparte, con scope de escritura, para no ampliar el de lectura.
#
# Un cliente NUEVO por llamada, no cacheado: httplib2 mantiene viva la conexión HTTP y,
# con la instancia de Cloud Run tibia entre una corrida horaria y la siguiente, el cliente
# reusaba un socket que Google ya había cerrado por inactividad -> `[Errno 32] Broken pipe`
# / `SSL: UNEXPECTED_EOF_WHILE_READING` (14 corridas fallidas el 2026-11-18/20, todas en
# horario laboral, cuando el resto del tráfico mantiene viva la instancia). Construirlo cuesta
# milisegundos (el discovery doc es estático); las credenciales sí se reusan.
# Además, `num_retries` reintenta con backoff los errores transitorios (5xx, 429, SSL,
# socket) — sin ese argumento googleapiclient no reintenta nada.
SHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
_WRITE_RETRIES = 3

_write_credentials = None
_write_credentials_lock = threading.Lock()


def _new_write_service():
    global _write_credentials
    with _write_credentials_lock:
        if _write_credentials is None:
            _write_credentials, _ = google.auth.default(scopes=[SHEETS_WRITE_SCOPE])
    return build("sheets", "v4", credentials=_write_credentials, cache_discovery=False)


def _update_and_clear_sync(
    spreadsheet_id: str, updates: list[tuple[str, list[list[Any]]]], clear_range: str
) -> None:
    values = _new_write_service().spreadsheets().values()
    if updates:
        values.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": [{"range": rng, "values": vals} for rng, vals in updates],
            },
        ).execute(num_retries=_WRITE_RETRIES)
    values.clear(spreadsheetId=spreadsheet_id, range=clear_range, body={}).execute(
        num_retries=_WRITE_RETRIES
    )


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
