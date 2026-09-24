"""Sincronización de solo lectura del Google Sheet "SEC. GAS PIT".

Fuente: dos pestañas del Sheet real —
  - "MATRIZ (NO TOMAR)", filtrada a SUB-TIPO DE OBRA = "E- OBRAS DE GAS".
  - "ACCIONES TERRITORIO", ya 100% Área = "Secretaría Gas" (sin filtro).

Ver spec: docs/files/spec-sync-gasifera-pit.md
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.gas_pit.models import (
    GasPitAccionTerritorio,
    GasPitObra,
    GasPitObraLocalidad,
    GasPitSyncLog,
)
from app.gas_pit.schemas import (
    AccionTerritorioResponse,
    ObraGasResponse,
    SyncErrorDetail,
    SyncResultResponse,
    SyncStatusResponse,
)
from app.integrations import google_sheets, notificaciones_vivienda

SUB_TIPO_GAS = "E- OBRAS DE GAS"

# Enums casi-duplicados detectados en el análisis del Sheet real — se colapsan al
# valor canónico (clave en mayúsculas para comparar case-insensitive).
ESTADO_OBRA_CANON = {
    "PROC. DE ADJUDICACION": "EN PROCESO DE ADJUDICACIÓN",
}
PRIORIDAD_CANON = {
    "OBRA CON PRESUPUESTO": "OBRAS CON PRESUPUESTO",
}

_SPIP_LIKE_DATE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
_LOCALIDAD_SEP = re.compile(r"\s+-\s+")


# ── Helpers de parseo tolerante (mismo estilo que cordon_cuneta/checklist_sync.py) ──

def _clean_str(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _clean_enum(raw: Any, mapping: dict[str, str]) -> str | None:
    s = _clean_str(raw)
    if s is None:
        return None
    return mapping.get(s.upper(), s)


def _clean_spip(raw: Any) -> str | None:
    s = _clean_str(raw)
    if s is None or s == "-":
        return None
    if _SPIP_LIKE_DATE.match(s):
        # Excel auto-convirtió el número a fecha por formato de celda heredado
        # (visto en el análisis del Excel real, ~80 casos). No se adivina el
        # valor original — queda NULL para revisión manual del área.
        return None
    return s


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
        return float(s)
    except ValueError:
        pass
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_fraction(raw: Any) -> float | None:
    """AVANCE viene como fracción 0-1 (a veces con '%' si alguien lo tipeó a mano)."""
    if raw is None or raw == "":
        return None
    s = str(raw).strip().replace("%", "")
    val = _parse_number(s)
    if val is None:
        return None
    return val / 100 if val > 1 else val


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


def _parse_bool_pit(raw: Any) -> bool:
    s = _clean_str(raw)
    return bool(s) and s.strip().upper() == "PIT"


def _split_localidades(raw: str) -> list[str]:
    """LOCALIDAD suele traer 2+ nombres concatenados (ej. "TANTI - EL DURAZNO")."""
    partes = [p.strip() for p in _LOCALIDAD_SEP.split(raw) if p.strip()]
    return partes or [raw.strip()]


def _row_dict(headers: list[str], row: list[Any]) -> dict[str, Any]:
    return {h: (row[i] if i < len(row) else None) for i, h in enumerate(headers) if h}


# ── Upsert: gas_pit_obras (+ localidades) ──────────────────────────────────────

async def _upsert_obra(db: AsyncSession, sheet_row_number: int, r: dict[str, Any]) -> bool:
    nombre_obra = _clean_str(r.get("NOMBRE DE OBRA"))
    departamento = _clean_str(r.get("DEPARTAMENTO"))
    nombre_norm = nombre_obra.strip().lower()
    depto_norm = (departamento or "").strip().lower()

    existing = (
        await db.execute(
            select(GasPitObra).where(
                GasPitObra.nombre_obra_norm == nombre_norm,
                GasPitObra.departamento_norm == depto_norm,
            )
        )
    ).scalar_one_or_none()

    is_new = existing is None
    obra = existing or GasPitObra(nombre_obra=nombre_obra, nombre_obra_norm=nombre_norm, departamento_norm=depto_norm)

    obra.nombre_obra = nombre_obra
    obra.nombre_obra_norm = nombre_norm
    obra.departamento_norm = depto_norm
    obra.spip = _clean_spip(r.get("SPIP"))
    obra.expediente = _clean_str(r.get("EXPEDIENTE"))
    obra.division = _clean_str(r.get("DIVISIÓN"))
    obra.tipo_obra = _clean_str(r.get("T. OBRA"))
    obra.sub_tipo_obra = _clean_str(r.get("SUB-TIPO DE OBRA")) or SUB_TIPO_GAS
    obra.contratista = _clean_str(r.get("CONTRATISTA"))
    obra.estado_obra = _clean_enum(r.get("ESTADO DE OBRA"), ESTADO_OBRA_CANON)
    obra.estado_resumen = _clean_str(r.get("ESTADO-RESUMEN"))
    obra.departamento = departamento
    obra.avance = _parse_fraction(r.get("AVANCE"))
    obra.repla_inicial = _parse_date(r.get("REPLA. INICIAL"))
    obra.fecha_lic = _parse_date(r.get("FECHA LIC"))
    obra.vencimiento = _parse_date(r.get("VENCIMIENTO"))
    obra.plazo_vigente_dias = _parse_int(r.get("PLAZO VIGENTE EN DÍAS"))
    obra.plazo_original = _parse_int(r.get("PLAZO ORIGINAL"))
    obra.contrato_base = _parse_number(r.get("CONTRATO BASE"))
    obra.ampliacion = _parse_number(r.get("AMPLIACION"))
    obra.enmienda = _parse_number(r.get("ENMIENDA"))
    obra.importe_obra_actualizado = _parse_number(r.get("IMPORTE DE OBRA ACTUALIZADO"))
    obra.importe_dolar = _parse_number(r.get("IMPORTE EN DÓLAR"))
    obra.prioridad = _clean_enum(r.get("PRIORIDAD"), PRIORIDAD_CANON)
    obra.categoria = _parse_int(r.get("CATEGORIA"))
    obra.region = _clean_str(r.get("REGION"))
    obra.autorizada_2025 = _clean_str(r.get("AUTORIZADA 2025"))
    obra.pit = _parse_bool_pit(r.get("PIT"))
    obra.sheet_row_number = sheet_row_number
    obra.last_synced_at = datetime.now(timezone.utc)

    if is_new:
        db.add(obra)
    await db.flush()  # asegura obra.id disponible para las localidades

    await db.execute(delete(GasPitObraLocalidad).where(GasPitObraLocalidad.obra_id == obra.id))
    localidad_raw = _clean_str(r.get("LOCALIDAD")) or ""
    for localidad in _split_localidades(localidad_raw):
        if localidad:
            db.add(GasPitObraLocalidad(obra_id=obra.id, localidad=localidad))
    await db.flush()

    return is_new


# ── Upsert: gas_pit_acciones_territorio ────────────────────────────────────────

async def _upsert_accion(db: AsyncSession, sheet_row_number: int, r: dict[str, Any]) -> bool:
    existing = (
        await db.execute(
            select(GasPitAccionTerritorio).where(
                GasPitAccionTerritorio.sheet_row_number == sheet_row_number
            )
        )
    ).scalar_one_or_none()

    is_new = existing is None
    accion = existing or GasPitAccionTerritorio(sheet_row_number=sheet_row_number)

    monto_solicitado = _parse_number(r.get("Monto Inversión solicitado"))

    accion.fecha = _parse_date(r.get("Fecha"))
    accion.departamento = _clean_str(r.get("Departamento"))
    accion.localidad = _clean_str(r.get("Localidad"))
    accion.ministerio = _clean_str(r.get("Ministerio"))
    accion.area = _clean_str(r.get("Área"))
    accion.id_accion = _clean_str(r.get("ID_ACCION"))
    accion.accion = _clean_str(r.get("Acción"))
    accion.detalle_accion = _clean_str(r.get("Detalle de la acción"))
    accion.estado = _clean_str(r.get("Estado")) or "Pendiente"
    accion.monto_inversion_solicitado = monto_solicitado
    accion.comentarios = _clean_str(r.get("Comentarios"))
    # monto_inversion_solicitado está en ARS (confirmado contra importe_obra_actualizado
    # de gas_pit_obras, mismo orden de magnitud) — para USD se DIVIDE por el tipo de
    # cambio (ARS por USD), no se multiplica. Bug real de Fase 0 corregido 2026-09-23,
    # ver spec-sync-gasifera-pit.md changelog.
    accion.monto_inversion_usd = (
        round(monto_solicitado / settings.tipo_cambio_usd, 2) if monto_solicitado is not None else None
    )
    accion.alerta_localidad = _clean_str(r.get("ALERTA_LOCALIDAD"))
    accion.sheet_row_number = sheet_row_number
    accion.last_synced_at = datetime.now(timezone.utc)

    if is_new:
        db.add(accion)
    await db.flush()

    return is_new


class SheetReadError(Exception):
    """El Sheet no pudo leerse (API caída, Sheet desvinculado, cuota, etc.).

    Distinto de un error de fila: acá no hay nada que procesar. Se loguea en
    gas_pit_sync_log igual que cualquier corrida, pero se re-lanza para que el
    endpoint devuelva un error HTTP real.
    """


async def _log_sync_failure(db: AsyncSession, started_at: datetime, triggered_by: str, motivo: str) -> None:
    log = GasPitSyncLog(
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        filas_leidas=0,
        filas_insertadas=0,
        filas_actualizadas=0,
        filas_error=1,
        errores=json.dumps([{"fila": 0, "hoja": "-", "motivo": motivo}], ensure_ascii=False),
        triggered_by=triggered_by,
    )
    db.add(log)
    await db.flush()


# ── Sync completo (ambas hojas en una corrida) ─────────────────────────────────

async def sync_from_sheet(db: AsyncSession, triggered_by: str = "manual") -> SyncResultResponse:
    started_at = datetime.now(timezone.utc)

    try:
        matriz_rows = await google_sheets.get_values(
            settings.google_sheet_gas_pit_id, settings.google_sheet_gas_pit_range_matriz
        )
        acciones_rows = await google_sheets.get_values(
            settings.google_sheet_gas_pit_id, settings.google_sheet_gas_pit_range_acciones
        )
    except Exception as exc:
        await _log_sync_failure(db, started_at, triggered_by, str(exc))
        raise SheetReadError(f"No se pudo leer el Google Sheet: {exc}") from exc

    filas_leidas = 0
    filas_insertadas = 0
    filas_actualizadas = 0
    errores: list[dict[str, Any]] = []
    nuevas_acciones: list[tuple[str | None, str | None, str | None]] = []

    # ── MATRIZ (NO TOMAR), filtrada a obras de gas ──
    if matriz_rows:
        headers = [_clean_str(h) or "" for h in matriz_rows[0]]
        for offset, row in enumerate(matriz_rows[1:]):
            sheet_row_number = offset + 2  # fila 1 = headers
            r = _row_dict(headers, row)
            nombre_obra = _clean_str(r.get("NOMBRE DE OBRA"))
            if not nombre_obra:
                continue  # fila en blanco
            sub_tipo = _clean_str(r.get("SUB-TIPO DE OBRA"))
            if not sub_tipo or sub_tipo.strip().upper() != SUB_TIPO_GAS:
                continue  # fuera de alcance (otra categoría de obra)

            filas_leidas += 1
            try:
                # SAVEPOINT por fila — ver spec §7 / lección de
                # spec-sync-cc-checklist-tecnico.md §13.5.
                async with db.begin_nested():
                    is_new = await _upsert_obra(db, sheet_row_number, r)
                filas_insertadas += is_new
                filas_actualizadas += not is_new
            except Exception as exc:  # una fila con error no debe frenar el resto del batch
                errores.append({
                    "fila": sheet_row_number, "hoja": "MATRIZ (NO TOMAR)",
                    "motivo": f"'{nombre_obra}': error al procesar la fila ({exc})",
                })

    # ── ACCIONES TERRITORIO (ya 100% gas) ──
    if acciones_rows:
        headers = [_clean_str(h) or "" for h in acciones_rows[0]]
        for offset, row in enumerate(acciones_rows[1:]):
            sheet_row_number = offset + 2
            r = _row_dict(headers, row)
            localidad = _clean_str(r.get("Localidad"))
            departamento = _clean_str(r.get("Departamento"))
            accion = _clean_str(r.get("Acción"))
            if not localidad and not accion:
                continue  # fila en blanco

            filas_leidas += 1
            try:
                async with db.begin_nested():
                    is_new = await _upsert_accion(db, sheet_row_number, r)
                filas_insertadas += is_new
                filas_actualizadas += not is_new
                if is_new:
                    nuevas_acciones.append((localidad, departamento, accion))
            except Exception as exc:
                errores.append({
                    "fila": sheet_row_number, "hoja": "ACCIONES TERRITORIO",
                    "motivo": f"'{localidad or accion}': error al procesar la fila ({exc})",
                })

    finished_at = datetime.now(timezone.utc)
    log = GasPitSyncLog(
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

    # Fuera del SAVEPOINT por fila y después del log — no atar la llamada HTTP a
    # svc-vivienda a la transacción de cada fila (ADR-023). Sólo ACCIONES
    # TERRITORIO tiene el campo "acción" pedido — MATRIZ/obras no genera alerta.
    for loc, dep, accion_nueva in nuevas_acciones:
        await notificaciones_vivienda.notificar_accion_nueva(
            localidad=loc, departamento=dep, accion=accion_nueva
        )

    return SyncResultResponse(
        filas_leidas=filas_leidas,
        filas_insertadas=filas_insertadas,
        filas_actualizadas=filas_actualizadas,
        filas_error=len(errores),
        errores=[SyncErrorDetail(**e) for e in errores],
    )


async def get_last_sync_status(db: AsyncSession) -> SyncStatusResponse | None:
    result = await db.execute(select(GasPitSyncLog).order_by(GasPitSyncLog.started_at.desc()).limit(1))
    log = result.scalar_one_or_none()
    if not log:
        return None
    return SyncStatusResponse.model_validate(log)


# ── Lectura (para el panel preliminar de solo lectura, spec §12) ───────────────

def _obra_to_response(obra: GasPitObra) -> ObraGasResponse:
    return ObraGasResponse(
        id=obra.id,
        spip=obra.spip,
        expediente=obra.expediente,
        division=obra.division,
        nombre_obra=obra.nombre_obra,
        tipo_obra=obra.tipo_obra,
        sub_tipo_obra=obra.sub_tipo_obra,
        contratista=obra.contratista,
        estado_obra=obra.estado_obra,
        estado_resumen=obra.estado_resumen,
        departamento=obra.departamento,
        localidades=[l.localidad for l in obra.localidades],
        avance=float(obra.avance) if obra.avance is not None else None,
        repla_inicial=obra.repla_inicial,
        fecha_lic=obra.fecha_lic,
        vencimiento=obra.vencimiento,
        plazo_vigente_dias=obra.plazo_vigente_dias,
        plazo_original=obra.plazo_original,
        contrato_base=float(obra.contrato_base) if obra.contrato_base is not None else None,
        ampliacion=float(obra.ampliacion) if obra.ampliacion is not None else None,
        enmienda=float(obra.enmienda) if obra.enmienda is not None else None,
        importe_obra_actualizado=(
            float(obra.importe_obra_actualizado) if obra.importe_obra_actualizado is not None else None
        ),
        importe_dolar=float(obra.importe_dolar) if obra.importe_dolar is not None else None,
        prioridad=obra.prioridad,
        categoria=obra.categoria,
        region=obra.region,
        autorizada_2025=obra.autorizada_2025,
        pit=obra.pit,
        last_synced_at=obra.last_synced_at,
    )


async def listar_obras(db: AsyncSession, limit: int, offset: int) -> tuple[list[ObraGasResponse], int]:
    total = (await db.execute(select(func.count()).select_from(GasPitObra))).scalar_one()
    result = await db.execute(
        select(GasPitObra)
        .options(selectinload(GasPitObra.localidades))
        .order_by(GasPitObra.nombre_obra)
        .limit(limit)
        .offset(offset)
    )
    obras = result.scalars().all()
    return [_obra_to_response(o) for o in obras], total


async def listar_acciones_territorio(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[AccionTerritorioResponse], int]:
    total = (await db.execute(select(func.count()).select_from(GasPitAccionTerritorio))).scalar_one()
    result = await db.execute(
        select(GasPitAccionTerritorio)
        .order_by(GasPitAccionTerritorio.fecha.desc().nulls_last(), GasPitAccionTerritorio.sheet_row_number)
        .limit(limit)
        .offset(offset)
    )
    acciones = result.scalars().all()
    return [AccionTerritorioResponse.model_validate(a) for a in acciones], total
