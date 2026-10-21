"""Sincronización de solo lectura del ATP Interno de Gobierno: pestaña "ATP ACUMULADO" de la
planilla "4. ATP 2026" (spec-atp-interno.md §3).

La planilla no tiene un id por fila y las filas se reordenan, así que cada corrida reemplaza
todo lo del año de la planilla en una transacción, con un freno contra una planilla vaciada por
error. El referente se guarda pero nunca se loguea ni se devuelve (§5).
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp_interno.models import AtpInternoPago, AtpInternoSyncLog
from app.config import settings
from app.integrations import google_sheets

# Menos de esta proporción de las filas de la carga anterior frena el reemplazo (§3).
FRENO_PROPORCION = 0.5
_OBLIGATORIAS = ("ID_LOC", "FECHA", "MONTO")


class SheetReadError(Exception):
    """No se pudo leer la planilla, o le faltan columnas: no hay nada que cargar."""


class AnomaliaOut(BaseModel):
    tipo: str
    fila: int | None = None
    detalle: str | None = None


class SyncInternoResponse(BaseModel):
    estado: str  # ok | error | frenado
    anio_planilla: int | None
    filas_leidas: int
    filas_cargadas: int
    filas_descartadas: int
    anomalias: list[AnomaliaOut]
    mensaje: str | None = None


class SyncInternoEstado(BaseModel):
    started_at: datetime
    finished_at: datetime | None
    estado: str
    anio_planilla: int | None
    filas_leidas: int
    filas_cargadas: int
    filas_descartadas: int
    mensaje: str | None
    triggered_by: str | None


# ── Parseo (puro, sin base) ───────────────────────────────────────────────────


def _clave(s: Any) -> str:
    s = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[\s_]+", "_", s).strip("_").upper()


def _texto(raw: Any, largo: int) -> str | None:
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    return s[:largo] or None


def codigo_indec(raw: Any) -> str | None:
    """`142007`, `142.007`, `"142,007"` → `"142007"`. None si no son 6 dígitos."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, float):
        if not raw.is_integer():
            return None
        raw = int(raw)
    digitos = re.sub(r"\D", "", str(raw))
    return digitos if len(digitos) == 6 else None


def monto(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace("$", "").replace(" ", "").strip()
    for candidato in (s, s.replace(".", "").replace(",", "."), s.replace(",", "")):
        try:
            return float(candidato)
        except ValueError:
            continue
    return None


def fecha(raw: Any) -> date | None:
    """Serial de planilla o texto `d/m/aaaa`. None si es imposible (p. ej. el serial 6693568)."""
    if isinstance(raw, bool) or raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        # 2000-01-01 a 2099-12-31: fuera de eso es un error de carga.
        return date(1899, 12, 30) + timedelta(days=int(raw)) if 36526 <= raw <= 73050 else None
    s = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class Parseo:
    filas: list[dict[str, Any]] = field(default_factory=list)
    leidas: int = 0
    descartadas: int = 0
    anomalias: list[AnomaliaOut] = field(default_factory=list)


def parsear(valores: list[list[Any]], anio_planilla: int) -> Parseo:
    """Encabezado en la primera fila; columnas ubicadas por nombre. Lanza SheetReadError si falta
    una obligatoria."""
    if not valores:
        return Parseo()
    enc = {_clave(h): i for i, h in enumerate(valores[0]) if _clave(h)}
    faltan = [c for c in _OBLIGATORIAS if c not in enc]
    if faltan:
        raise SheetReadError(f"Faltan columnas en la planilla: {', '.join(faltan)}")

    def celda(fila: list[Any], col: str) -> Any:
        i = enc.get(col)
        return fila[i] if i is not None and i < len(fila) else None

    p = Parseo()
    nombres: dict[str, set[str]] = {}
    for n, fila in enumerate(valores[1:], start=2):
        if all(c in (None, "") for c in fila):
            continue
        p.leidas += 1
        cod = codigo_indec(celda(fila, "ID_LOC"))
        m = monto(celda(fila, "MONTO"))
        if cod is None:
            p.descartadas += 1
            p.anomalias.append(AnomaliaOut(tipo="sin_codigo", fila=n))
            continue
        if m is None or m <= 0:
            p.descartadas += 1
            p.anomalias.append(AnomaliaOut(tipo="sin_monto", fila=n))
            continue
        f = fecha(celda(fila, "FECHA"))
        if f is None:
            p.anomalias.append(AnomaliaOut(tipo="fecha_invalida", fila=n, detalle=f"se cuenta en {anio_planilla}"))
        localidad = _texto(celda(fila, "LOCALIDAD"), 150)
        if localidad:
            nombres.setdefault(cod, set()).add(localidad.upper())
        p.filas.append(
            dict(
                fila=n,
                codigo_indec=cod,
                localidad=localidad,
                departamento=_texto(celda(fila, "DEPARTAMENTO"), 100),
                fecha=f,
                anio=f.year if f else anio_planilla,
                monto=m,
                referente=_texto(celda(fila, "REFERENTE"), 120),
            )
        )
    for cod, ns in sorted(nombres.items()):
        if len(ns) > 1:
            p.anomalias.append(AnomaliaOut(tipo="codigo_con_mas_de_un_nombre", detalle=f"{cod}: {len(ns)} nombres"))
    return p


# ── Corrida ───────────────────────────────────────────────────────────────────


async def _log(db: AsyncSession, inicio: datetime, triggered_by: str, r: SyncInternoResponse) -> SyncInternoResponse:
    db.add(
        AtpInternoSyncLog(
            started_at=inicio,
            finished_at=datetime.now(timezone.utc),
            estado=r.estado,
            anio_planilla=r.anio_planilla,
            filas_leidas=r.filas_leidas,
            filas_cargadas=r.filas_cargadas,
            filas_descartadas=r.filas_descartadas,
            anomalias=json.dumps([a.model_dump(exclude_none=True) for a in r.anomalias], ensure_ascii=False),
            mensaje=r.mensaje,
            triggered_by=triggered_by,
        )
    )
    await db.flush()
    return r


async def sync_atp_interno(db: AsyncSession, triggered_by: str = "manual") -> SyncInternoResponse:
    """Devuelve el resultado con `estado = error` si no se pudo leer (el router responde 502);
    el log se escribe igual, porque el router no propaga la excepción y la sesión se commitea."""
    inicio = datetime.now(timezone.utc)
    anio = settings.atp_interno_anio_planilla
    vacio = dict(anio_planilla=anio, filas_leidas=0, filas_cargadas=0, filas_descartadas=0, anomalias=[])
    try:
        if not settings.google_sheet_atp_interno_id:
            raise SheetReadError("GOOGLE_SHEET_ATP_INTERNO_ID no está configurado")
        try:
            valores = await google_sheets.get_values(
                settings.google_sheet_atp_interno_id, settings.google_sheet_atp_interno_rango, sin_formato=True
            )
        except Exception as exc:  # noqa: BLE001 — API caída, planilla no compartida, cuota
            raise SheetReadError(f"No se pudo leer la planilla: {exc}") from exc
        p = parsear(valores, anio)
    except SheetReadError as exc:
        return await _log(db, inicio, triggered_by, SyncInternoResponse(estado="error", mensaje=str(exc), **vacio))

    anterior = (
        await db.execute(select(func.count()).select_from(AtpInternoPago).where(AtpInternoPago.anio_planilla == anio))
    ).scalar_one()
    base = dict(
        anio_planilla=anio, filas_leidas=p.leidas, filas_descartadas=p.descartadas, anomalias=p.anomalias
    )
    if not p.filas or (anterior and len(p.filas) < anterior * FRENO_PROPORCION):
        msg = f"La planilla trae {len(p.filas)} filas válidas contra {anterior} de la carga anterior: no se reemplaza nada"
        return await _log(db, inicio, triggered_by, SyncInternoResponse(estado="frenado", filas_cargadas=0, mensaje=msg, **base))

    await db.execute(delete(AtpInternoPago).where(AtpInternoPago.anio_planilla == anio))
    ahora = datetime.now(timezone.utc)
    db.add_all(AtpInternoPago(anio_planilla=anio, last_synced_at=ahora, **f) for f in p.filas)
    await db.flush()
    return await _log(db, inicio, triggered_by, SyncInternoResponse(estado="ok", filas_cargadas=len(p.filas), **base))


async def estado_sync(db: AsyncSession) -> SyncInternoEstado | None:
    log = (
        await db.execute(select(AtpInternoSyncLog).order_by(AtpInternoSyncLog.started_at.desc()).limit(1))
    ).scalar_one_or_none()
    if log is None:
        return None
    return SyncInternoEstado(
        started_at=log.started_at,
        finished_at=log.finished_at,
        estado=log.estado,
        anio_planilla=log.anio_planilla,
        filas_leidas=log.filas_leidas,
        filas_cargadas=log.filas_cargadas,
        filas_descartadas=log.filas_descartadas,
        mensaje=log.mensaje,
        triggered_by=log.triggered_by,
    )
