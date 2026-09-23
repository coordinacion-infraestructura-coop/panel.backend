"""Sincronización de solo lectura de la hoja "BD" del Google Sheet
"ATP - Compromiso Gobernador" (compromisos de Aporte del Tesoro Provincial +
cronograma de pago mensual).

Ver spec: docs/files/spec-sync-atp-compromiso-gobernador.md
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp.models import AtpCompromiso, AtpCronogramaPago, AtpSyncLog
from app.atp.schemas import (
    CompromisoResponse,
    CronogramaPagoResponse,
    SyncErrorDetail,
    SyncResultResponse,
    SyncStatusResponse,
)
from app.config import settings
from app.integrations import google_sheets

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_MES_RE = re.compile(r"^([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+(\d{2})$")

# Columnas fijas de la hoja "BD" — cualquier otro encabezado se intenta
# parsear como columna mensual del cronograma (ver _parse_periodo). Esto
# hace que agregar una columna "Enero 28" a la derecha se sincronice solo,
# sin requerir un cambio de código (ver spec §3.1).
_CAMPOS_FIJOS = {
    "", "DEPARTAMENTO", "LOCALIDAD", "Ministerio", "Fecha de anuncio",
    "Nro. Expediente", "Derivado", "Monto", "Destino", "SALDO ATP",
    "IGNORAR", "CUOTA SIN ASIGNAR",
}


# ── Helpers de parseo tolerante (mismo estilo que gas_pit/sync.py) ────────────

def _clean_str(raw: Any) -> str | None:
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    return s or None


def _parse_number(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("$", "").replace(" ", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    s = _clean_str(raw)
    return bool(s) and s.upper() in {"TRUE", "VERDADERO", "1"}


def _parse_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        try:
            return date(1899, 12, 30) + timedelta(days=int(raw))
        except (OverflowError, ValueError):
            return None
    s = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_periodo(header: str) -> date | None:
    """Header tipo "Marzo 25" -> date(2025, 3, 1). Genérico a propósito (ver
    _CAMPOS_FIJOS)."""
    m = _MES_RE.match(header.strip())
    if not m:
        return None
    mes = _MESES.get(m.group(1).lower())
    if mes is None:
        return None
    return date(2000 + int(m.group(2)), mes, 1)


def _row_dict(headers: list[str], row: list[Any]) -> dict[str, Any]:
    return {h: (row[i] if i < len(row) else None) for i, h in enumerate(headers) if h}


# ── Upsert: atp_compromisos (+ cronograma) ────────────────────────────────────

async def _upsert_compromiso(db: AsyncSession, sheet_row_number: int, r: dict[str, Any]) -> bool:
    existing = (
        await db.execute(select(AtpCompromiso).where(AtpCompromiso.sheet_row_number == sheet_row_number))
    ).scalar_one_or_none()

    is_new = existing is None
    compromiso = existing or AtpCompromiso(sheet_row_number=sheet_row_number)

    compromiso.departamento = _clean_str(r.get("DEPARTAMENTO"))
    compromiso.localidad = _clean_str(r.get("LOCALIDAD"))
    compromiso.ministerio_destino = _clean_str(r.get("Ministerio"))
    compromiso.fecha_anuncio = _parse_date(r.get("Fecha de anuncio"))
    compromiso.nro_expediente = _clean_str(r.get("Nro. Expediente"))
    compromiso.derivado = _parse_bool(r.get("Derivado"))
    compromiso.monto = _parse_number(r.get("Monto"))
    compromiso.destino = _clean_str(r.get("Destino"))
    compromiso.saldo_atp = _parse_number(r.get("SALDO ATP"))
    compromiso.sheet_row_number = sheet_row_number
    compromiso.last_synced_at = datetime.now(timezone.utc)

    if is_new:
        db.add(compromiso)
    await db.flush()  # asegura compromiso.id disponible para el cronograma

    await db.execute(delete(AtpCronogramaPago).where(AtpCronogramaPago.compromiso_id == compromiso.id))
    for header, raw in r.items():
        if header in _CAMPOS_FIJOS:
            continue
        periodo = _parse_periodo(header)
        if periodo is None:
            continue  # encabezado desconocido, no matchea patrón de mes
        monto_mes = _parse_number(raw)
        if monto_mes is None:
            continue  # celda vacía ese mes, no se persiste una fila en 0
        db.add(AtpCronogramaPago(compromiso_id=compromiso.id, periodo=periodo, monto=monto_mes))
    await db.flush()

    return is_new


class SheetReadError(Exception):
    """El Sheet no pudo leerse (API caída, Sheet desvinculado, cuota, etc.).

    Distinto de un error de fila: acá no hay nada que procesar. Se loguea en
    atp_sync_log igual que cualquier corrida, pero se re-lanza para que el
    endpoint devuelva un error HTTP real.
    """


async def _log_sync_failure(db: AsyncSession, started_at: datetime, triggered_by: str, motivo: str) -> None:
    log = AtpSyncLog(
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        filas_leidas=0,
        filas_insertadas=0,
        filas_actualizadas=0,
        filas_error=1,
        errores=json.dumps([{"fila": 0, "motivo": motivo}], ensure_ascii=False),
        triggered_by=triggered_by,
    )
    db.add(log)
    await db.flush()


# ── Sync completo (una única hoja: "BD") ──────────────────────────────────────

async def sync_from_sheet(db: AsyncSession, triggered_by: str = "manual") -> SyncResultResponse:
    started_at = datetime.now(timezone.utc)

    try:
        rows = await google_sheets.get_values(settings.google_sheet_atp_id, settings.google_sheet_atp_range_bd)
    except Exception as exc:
        await _log_sync_failure(db, started_at, triggered_by, str(exc))
        raise SheetReadError(f"No se pudo leer el Google Sheet: {exc}") from exc

    filas_leidas = 0
    filas_insertadas = 0
    filas_actualizadas = 0
    errores: list[dict[str, Any]] = []

    if rows:
        headers = [(_clean_str(h) or "") for h in rows[0]]
        header_row_number = settings.google_sheet_atp_header_row
        for offset, row in enumerate(rows[1:]):
            sheet_row_number = header_row_number + 1 + offset
            r = _row_dict(headers, row)
            departamento = _clean_str(r.get("DEPARTAMENTO"))
            localidad = _clean_str(r.get("LOCALIDAD"))
            if not departamento and not localidad:
                continue  # fila en blanco

            filas_leidas += 1
            try:
                # SAVEPOINT por fila — ver spec §4 / lección de
                # spec-sync-cc-checklist-tecnico.md §13.5.
                async with db.begin_nested():
                    is_new = await _upsert_compromiso(db, sheet_row_number, r)
                filas_insertadas += is_new
                filas_actualizadas += not is_new
            except Exception as exc:  # una fila con error no debe frenar el resto del batch
                errores.append({
                    "fila": sheet_row_number,
                    "motivo": f"'{localidad or departamento}': error al procesar la fila ({exc})",
                })

    finished_at = datetime.now(timezone.utc)
    log = AtpSyncLog(
        started_at=started_at,
        finished_at=finished_at,
        filas_leidas=filas_leidas,
        filas_insertadas=filas_insertadas,
        filas_actualizadas=filas_actualizadas,
        filas_error=len(errores),
        errores=json.dumps(errores, ensure_ascii=False),
        triggered_by=triggered_by,
    )
    db.add(log)
    await db.flush()

    return SyncResultResponse(
        filas_leidas=filas_leidas,
        filas_insertadas=filas_insertadas,
        filas_actualizadas=filas_actualizadas,
        filas_error=len(errores),
        errores=[SyncErrorDetail(**e) for e in errores],
    )


async def get_last_sync_status(db: AsyncSession) -> SyncStatusResponse | None:
    result = await db.execute(select(AtpSyncLog).order_by(AtpSyncLog.started_at.desc()).limit(1))
    log = result.scalar_one_or_none()
    if not log:
        return None
    return SyncStatusResponse.model_validate(log)


# ── Lectura (para el panel preliminar de solo lectura, spec §12) ───────────────

async def listar_compromisos(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[CompromisoResponse], int]:
    total = (await db.execute(select(func.count()).select_from(AtpCompromiso))).scalar_one()
    result = await db.execute(
        select(AtpCompromiso)
        .order_by(AtpCompromiso.departamento, AtpCompromiso.localidad)
        .limit(limit)
        .offset(offset)
    )
    compromisos = result.scalars().all()

    # Suma del cronograma por compromiso, en una sola query aparte (no un
    # eager-load fila por fila) — evita traer hasta 34+ filas por compromiso
    # solo para un total.
    pagado_por_id: dict[str, float] = {}
    ids = [c.id for c in compromisos]
    if ids:
        rows = await db.execute(
            select(AtpCronogramaPago.compromiso_id, func.sum(AtpCronogramaPago.monto))
            .where(AtpCronogramaPago.compromiso_id.in_(ids))
            .group_by(AtpCronogramaPago.compromiso_id)
        )
        pagado_por_id = {cid: float(suma) for cid, suma in rows.all()}

    items = [
        CompromisoResponse(
            id=c.id,
            departamento=c.departamento,
            localidad=c.localidad,
            ministerio_destino=c.ministerio_destino,
            fecha_anuncio=c.fecha_anuncio,
            nro_expediente=c.nro_expediente,
            derivado=c.derivado,
            monto=float(c.monto) if c.monto is not None else None,
            destino=c.destino,
            saldo_atp=float(c.saldo_atp) if c.saldo_atp is not None else None,
            total_pagado=pagado_por_id.get(c.id),
            last_synced_at=c.last_synced_at,
        )
        for c in compromisos
    ]
    return items, total


async def obtener_cronograma(db: AsyncSession, compromiso_id: str) -> list[CronogramaPagoResponse] | None:
    """None si el compromiso no existe (el router lo traduce a 404); lista
    vacía si existe pero no tiene cronograma cargado."""
    existe = (
        await db.execute(select(AtpCompromiso.id).where(AtpCompromiso.id == compromiso_id))
    ).scalar_one_or_none()
    if existe is None:
        return None

    result = await db.execute(
        select(AtpCronogramaPago)
        .where(AtpCronogramaPago.compromiso_id == compromiso_id)
        .order_by(AtpCronogramaPago.periodo)
    )
    return [
        CronogramaPagoResponse(periodo=r.periodo, monto=float(r.monto))
        for r in result.scalars().all()
    ]
