"""Sincronización del checklist técnico de Cordón Cuneta desde el Google Sheet
"Base TOTAL". Ver spec: docs/files/spec-sync-cc-checklist-tecnico.md
"""
import json
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.cordon_cuneta.checklist_models import ChecklistItemCC, ChecklistTecnicoCC, SyncLogCC
from app.cordon_cuneta.checklist_schemas import (
    ChecklistTecnicoResponse,
    SyncErrorDetail,
    SyncResultResponse,
)
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.integrations import google_sheets

# Rango leído: "Base TOTAL!A6:AR400" — fila 6 es la primera con datos reales.
START_ROW = 6

# Columnas 0-based dentro del rango (A=0 ... AR=43)
COL_LOCALIDAD = 0
COL_DEPARTAMENTO = 1
COL_EXPEDIENTE = 2
COL_ORDEN = 3
COL_TIPO = 4
COL_INTENDENTE = 5
COL_TELEFONO = 6
COL_EMAIL = 7
COL_CONTACTO_TECNICO = 8
COL_MONTO_CONVENIO = 9
COL_CC_ML = 10
COL_ADOQUINADO_M2 = 11
FIRST_ITEM_COL = 12  # columna M — primer ítem del checklist (19 columnas: M..AE)
COL_ESTADO_EXPEDIENTE = 31
COL_OBSERVACIONES = 32
COL_FECHA_RADICACION = 33
COL_REPARTICION = 34

# Marcador literal que el área técnica usa para indicar el fin de los datos cargados.
_FIN_DATOS_MARKER = "AGREGAR NUEVAS LOCALIDADES"

# Los 19 ítems del checklist, en el orden en que aparecen las columnas M..AE.
# Etiquetas obtenidas de los comentarios de celda de la fila 3 del Sheet (bloques 1 y 3)
# y del propio encabezado de fila 3 (bloque 2, con nombre propio).
CHECKLIST_ITEMS: list[tuple[int, str]] = [
    (1, "Nota Solicitud de Financiamiento"),
    (2, "Ordenanza y Decreto/Resolución comunal"),
    (3, "DDJJ compromiso de ejecución de obra"),
    (4, "Proyecto, Planos, Cómputo y Presupuesto"),
    (5, "Descripción General"),
    (6, "Memoria Técnica"),
    (7, "Plazo de Ejecución"),
    (8, "Cómputo y Presupuesto"),
    (9, "Cronograma Avance Obra"),
    (10, "Planimetría"),
    (11, "Perfil Calzada"),
    (12, "Detalle de Cordón Cuneta"),
    (13, "Detalle de Badén"),
    (14, "Paquete estructural de Calzada"),
    (15, "Nota a Contaduría — Cesión Coparticipación"),
    (16, "N° CBU de M/C especial para depósito de fondos"),
    (17, "N° CUIT Municipal/Comunal"),
    (18, "DNI Intendente/Jefe Comunal"),
    (19, "Acta de Proclamación Intendente/Presidente Comunal"),
]


# ── Helpers de parseo tolerante ────────────────────────────────────────────────

def _cell(row: list[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def _clean_str(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _parse_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _parse_number(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("$", "").replace(" ", "")
    if not s:
        return None
    try:
        # Formato numérico plano (ya viene sin separadores si la API lo tipó como número)
        return float(s)
    except ValueError:
        pass
    try:
        # Fallback: formato es-AR "1.234.567,89"
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


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


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize_name(s: str) -> str:
    return _strip_accents(s).strip().lower()


# ── Matching best-effort contra viv_cordon_cuneta ──────────────────────────────

async def _match_municipio_id(
    db: AsyncSession, expediente: str | None, localidad: str
) -> str | None:
    if expediente:
        norm_exp = expediente.strip().lower()
        result = await db.execute(
            select(MunicipioCordonCuneta.id).where(
                MunicipioCordonCuneta.deleted_at.is_(None),
                func.lower(func.trim(MunicipioCordonCuneta.expediente)) == norm_exp,
            )
        )
        match = result.scalar_one_or_none()
        if match:
            return match

    norm_localidad = _normalize_name(localidad)
    result = await db.execute(
        select(MunicipioCordonCuneta.id, MunicipioCordonCuneta.municipio).where(
            MunicipioCordonCuneta.deleted_at.is_(None)
        )
    )
    for mid, municipio_nombre in result.all():
        if _normalize_name(municipio_nombre) == norm_localidad:
            return mid
    return None


# ── Upsert de una fila ──────────────────────────────────────────────────────────

async def _upsert_row(
    db: AsyncSession, sheet_row_number: int, localidad: str, departamento: str, row: list[Any]
) -> bool:
    """Crea o actualiza el checklist técnico de una localidad. Devuelve True si fue insert."""
    expediente = _clean_str(_cell(row, COL_EXPEDIENTE))
    municipio_id = await _match_municipio_id(db, expediente, localidad)

    norm_localidad = localidad.strip().lower()
    norm_departamento = departamento.strip().lower()
    existing = (
        await db.execute(
            select(ChecklistTecnicoCC).where(
                func.lower(func.trim(ChecklistTecnicoCC.localidad)) == norm_localidad,
                func.lower(func.trim(func.coalesce(ChecklistTecnicoCC.departamento, "")))
                == norm_departamento,
            )
        )
    ).scalar_one_or_none()

    is_new = existing is None
    checklist = existing or ChecklistTecnicoCC(localidad=localidad, departamento=departamento)

    checklist.localidad = localidad
    checklist.departamento = departamento
    checklist.expediente = expediente
    checklist.orden_sheet = _parse_int(_cell(row, COL_ORDEN))
    checklist.tipo = _clean_str(_cell(row, COL_TIPO))
    checklist.intendente = _clean_str(_cell(row, COL_INTENDENTE))
    checklist.telefono = _clean_str(_cell(row, COL_TELEFONO))
    checklist.email = _clean_str(_cell(row, COL_EMAIL))
    checklist.contacto_tecnico = _clean_str(_cell(row, COL_CONTACTO_TECNICO))
    checklist.monto_convenio = _parse_number(_cell(row, COL_MONTO_CONVENIO))
    checklist.cordon_cuneta_ml = _parse_number(_cell(row, COL_CC_ML))
    checklist.adoquinado_m2 = _parse_number(_cell(row, COL_ADOQUINADO_M2))
    checklist.estado_expediente = _clean_str(_cell(row, COL_ESTADO_EXPEDIENTE))
    checklist.observaciones = _clean_str(_cell(row, COL_OBSERVACIONES))
    checklist.fecha_radicacion = _parse_date(_cell(row, COL_FECHA_RADICACION))
    checklist.reparticion = _clean_str(_cell(row, COL_REPARTICION))
    checklist.municipio_id = municipio_id
    checklist.sheet_row_number = sheet_row_number
    checklist.last_synced_at = datetime.now(timezone.utc)

    if is_new:
        db.add(checklist)
    await db.flush()  # asegura checklist.id disponible para los items

    await db.execute(delete(ChecklistItemCC).where(ChecklistItemCC.checklist_id == checklist.id))
    for col_offset, (item_num, label) in enumerate(CHECKLIST_ITEMS):
        valor = _clean_str(_cell(row, FIRST_ITEM_COL + col_offset))
        if valor:
            db.add(
                ChecklistItemCC(
                    checklist_id=checklist.id, item_num=item_num, item_label=label, valor=valor
                )
            )
    await db.flush()

    return is_new


async def _log_sync_failure(
    db: AsyncSession, started_at: datetime, triggered_by: str, motivo: str
) -> None:
    log = SyncLogCC(
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


class SheetReadError(Exception):
    """El Sheet no pudo leerse (API caída, Sheet desvinculado de la SA, cuota, etc.).

    Distinto de un error de fila: acá no hay nada que procesar. Se loguea en
    viv_cc_sync_log igual que cualquier corrida, pero se re-lanza para que el
    endpoint devuelva un error HTTP real — es la señal que dispara la alerta
    de Cloud Monitoring (ver docs/files/spec-sync-cc-checklist-tecnico.md §14).
    """


# ── Sync completo ────────────────────────────────────────────────────────────────

async def sync_from_sheet(db: AsyncSession, triggered_by: str = "manual") -> SyncResultResponse:
    started_at = datetime.now(timezone.utc)

    try:
        raw_rows = await google_sheets.get_values(
            settings.google_sheet_cc_id, settings.google_sheet_cc_range
        )
    except Exception as exc:
        await _log_sync_failure(db, started_at, triggered_by, str(exc))
        raise SheetReadError(f"No se pudo leer el Google Sheet: {exc}") from exc

    filas_leidas = 0
    filas_insertadas = 0
    filas_actualizadas = 0
    errores: list[dict[str, Any]] = []

    for offset, row in enumerate(raw_rows):
        sheet_row_number = START_ROW + offset
        localidad_raw = _clean_str(_cell(row, COL_LOCALIDAD))
        if not localidad_raw:
            continue  # fila en blanco, se ignora silenciosamente

        if _FIN_DATOS_MARKER in localidad_raw.upper():
            break  # marcador de fin de datos cargadas por el área técnica

        filas_leidas += 1
        departamento = _clean_str(_cell(row, COL_DEPARTAMENTO))

        if not departamento:
            errores.append({
                "fila": sheet_row_number,
                "motivo": f"'{localidad_raw}': falta departamento (alta incompleta en el Sheet)",
            })
            continue

        try:
            is_new = await _upsert_row(db, sheet_row_number, localidad_raw, departamento, row)
            if is_new:
                filas_insertadas += 1
            else:
                filas_actualizadas += 1
        except Exception as exc:  # una fila con error no debe frenar el resto del batch
            errores.append({
                "fila": sheet_row_number,
                "motivo": f"'{localidad_raw}': error al procesar la fila ({exc})",
            })

    finished_at = datetime.now(timezone.utc)
    log = SyncLogCC(
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


# ── Lectura (para el panel) ───────────────────────────────────────────────────────

async def obtener_checklist_tecnico(
    db: AsyncSession, municipio_id: str
) -> ChecklistTecnicoResponse | None:
    result = await db.execute(
        select(ChecklistTecnicoCC)
        .options(selectinload(ChecklistTecnicoCC.items))
        .where(ChecklistTecnicoCC.municipio_id == municipio_id)
    )
    checklist = result.scalar_one_or_none()
    if not checklist:
        return None
    return ChecklistTecnicoResponse.model_validate(checklist)
