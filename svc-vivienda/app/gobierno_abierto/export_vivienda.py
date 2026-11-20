"""Exportación de pagos de Vivienda (CC/CH/ML) a la pestaña "Vivienda" de la planilla de
Gobierno Abierto.

Spec: docs/files/spec-export-gobierno-abierto-vivienda.md · ADR-034.

La pestaña es un espejo: cada corrida reescribe `B1:Q` completa desde `db_vivienda` y borra
las filas sobrantes. La columna A nunca se toca. Una fila por obra con el anticipo pagado.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AuthUser
from app.checklist_tecnico import catalog
from app.checklist_tecnico.models import ChecklistObraHito, ChecklistTecnico
from app.config import settings
from app.cordoba_hogar.models import LocalidadCordobaHogar
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.database import AsyncSessionLocal
from app.geo.models import GeoLocalidad
from app.gobierno_abierto.models import GobAbiertoSyncLog
from app.integrations import google_sheets
from app.mi_lugar.models import ProyectoML
from app.notificaciones import service as notificaciones_service

logger = logging.getLogger(__name__)

_SYNC_ACTOR = AuthUser(uid="gobabierto-sync", email="gobabierto-sync", role="system", secretarias=[])

PROGRAMA_NOMBRE = {"cc": "Cordón Cuneta", "ch": "Córdoba Hogar", "ml": "Mi Lugar"}

ENCABEZADOS = [
    "Localidad",
    "Departamento",
    "Programa",
    "Fecha anticipo financiero",
    "Monto anticipo",
    "Cuotas restantes",
    "Monto restante",
    "Avance físico 40% - fecha pago",
    "Avance físico 40% - monto",
    "Avance físico 70% - fecha pago",
    "Avance físico 70% - monto",
    "Avance físico 100% - fecha pago",
    "Avance físico 100% - monto",
    "Monto convenio",
    "Id sistema",
    "Detalle",
]

_HITOS_POSTERIORES = ("40", "70", "100")


class GobAbiertoSyncError(Exception):
    """Falló la escritura en la planilla (Sheets API caída, planilla no compartida, etc.).

    `es_permiso` distingue un rechazo real de Google (403/404: planilla no compartida o
    inexistente) de una falla transitoria de red, para no mandar a revisar el compartido
    cuando el problema es otro.
    """

    def __init__(self, mensaje: str, es_permiso: bool = False) -> None:
        super().__init__(mensaje)
        self.es_permiso = es_permiso


def _status_http(exc: Exception) -> int | None:
    """Código HTTP de un `googleapiclient.errors.HttpError`, o None si no es una respuesta."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _mensaje_falla(exc: GobAbiertoSyncError) -> str:
    base = f"No se pudieron escribir los pagos de Vivienda en la planilla de Gobierno Abierto: {str(exc)[:300]}."
    if exc.es_permiso:
        return (
            f"{base} Google rechazó el acceso: revisar que la planilla siga compartida como "
            "Editor con svc-vivienda@gestorcooperativo.iam.gserviceaccount.com y que la "
            f"pestaña \"{settings.gobabierto_sheet_tab}\" exista."
        )
    return f"{base} Parece una falla transitoria de conexión con Google; se reintenta en la próxima corrida horaria."


@dataclass(frozen=True)
class EntidadExport:
    programa: str
    entidad_id: str
    localidad: str
    departamento: str
    monto: float | None
    nombre_proyecto: str | None = None
    detalle: str = ""


# ── Armado de filas (puro) ──────────────────────────────────────────────────────

def _cantidad(v) -> str:
    """Número en formato argentino: 1.200 / 1.234,5 (sin decimales si es entero)."""
    f = float(v)
    if f == int(f):
        return f"{int(f):,}".replace(",", ".")
    entero, dec = f"{f:,.2f}".rstrip("0").split(".")
    return f"{entero.replace(',', '.')},{dec}"


def detalle_entidad(programa: str, e) -> str:
    """Cantidades físicas de la obra para la columna "Detalle" (spec §3.1, col Q)."""
    partes: list[str] = []
    if programa == "cc":
        if e.cordon_cuneta_ml:
            partes.append(f"{_cantidad(e.cordon_cuneta_ml)} m de cordón cuneta")
        if e.adoquinado_m2:
            partes.append(f"{_cantidad(e.adoquinado_m2)} m² de adoquinado")
    elif programa == "ch":
        if e.cantidad_casas:
            n = int(e.cantidad_casas)
            partes.append(f"{_cantidad(n)} vivienda{'s' if n != 1 else ''}")
    else:  # ml
        if e.lotes:
            n = int(e.lotes)
            partes.append(f"{_cantidad(n)} lote{'s' if n != 1 else ''}")
        if e.superficie:
            partes.append(f"{_cantidad(e.superficie)} ha")
    return " · ".join(partes)


def _fecha(d: date | None) -> str:
    return d.isoformat() if d else ""


def _num(v: float | None) -> float | str:
    return v if v is not None else ""


def armar_fila(entidad: EntidadExport, pagos: dict[str, date | None]) -> list[Any] | None:
    """Fila B:Q de una obra, o None si el anticipo no está pagado (no va a la planilla)."""
    fecha_anticipo = pagos.get("anticipo")
    if fecha_anticipo is None:
        return None

    def monto(tipo: str) -> float | None:
        return catalog.monto_hito(tipo, entidad.monto)

    pendientes = [t for t in _HITOS_POSTERIORES if pagos.get(t) is None]
    cuotas_restantes = ", ".join(catalog.HITOS_LABEL[t] for t in pendientes) or "Ninguna"
    if entidad.monto is None:
        monto_restante: float | None = None
    else:
        monto_restante = round(sum(monto(t) or 0.0 for t in pendientes), 2)

    fila: list[Any] = [
        entidad.localidad,
        entidad.departamento,
        PROGRAMA_NOMBRE[entidad.programa],
        _fecha(fecha_anticipo),
        _num(monto("anticipo")),
        cuotas_restantes,
        _num(monto_restante),
    ]
    for tipo in _HITOS_POSTERIORES:
        pagado = pagos.get(tipo)
        fila.append(_fecha(pagado))
        fila.append(_num(monto(tipo)) if pagado else "")
    fila.append(_num(entidad.monto))
    id_sistema = f"{entidad.programa.upper()}-{entidad.entidad_id}"
    if entidad.nombre_proyecto:
        id_sistema += f" · {entidad.nombre_proyecto}"
    fila.append(id_sistema)
    fila.append(entidad.detalle)
    return fila


def ordenar_filas(filas: list[list[Any]]) -> list[list[Any]]:
    # Fecha de anticipo (ISO, ordena como texto), localidad, id.
    return sorted(filas, key=lambda f: (f[3], f[0].lower(), f[14]))


# ── Lectura de la base ──────────────────────────────────────────────────────────

async def _entidades(db: AsyncSession, ids: dict[str, set[str]]) -> dict[tuple[str, str], EntidadExport]:
    geo_ids: set[str] = set()
    crudas: list[tuple[str, Any]] = []
    for programa, model in (("cc", MunicipioCordonCuneta), ("ch", LocalidadCordobaHogar), ("ml", ProyectoML)):
        if not ids.get(programa):
            continue
        result = await db.execute(
            select(model).where(model.id.in_(ids[programa]), model.deleted_at.is_(None))
        )
        for e in result.scalars():
            crudas.append((programa, e))
            if e.localidad_id:
                geo_ids.add(e.localidad_id)

    geo: dict[str, GeoLocalidad] = {}
    if geo_ids:
        result = await db.execute(select(GeoLocalidad).where(GeoLocalidad.id_geo.in_(geo_ids)))
        geo = {g.id_geo: g for g in result.scalars()}

    out: dict[tuple[str, str], EntidadExport] = {}
    for programa, e in crudas:
        nombre_libre = {"cc": lambda: e.municipio, "ch": lambda: e.localidad, "ml": lambda: e.localidad_nombre}[programa]()
        g = geo.get(e.localidad_id) if e.localidad_id else None
        out[(programa, e.id)] = EntidadExport(
            programa=programa,
            entidad_id=e.id,
            localidad=g.localidad if g else (nombre_libre or ""),
            departamento=g.departamento if g else (e.departamento or ""),
            monto=float(e.monto) if e.monto is not None else None,
            nombre_proyecto=(e.nombre or None) if programa == "ml" else None,
            detalle=detalle_entidad(programa, e),
        )
    return out


async def construir_filas(db: AsyncSession) -> list[list[Any]]:
    result = await db.execute(
        select(ChecklistTecnico.programa, ChecklistTecnico.entidad_id, ChecklistObraHito.tipo,
               ChecklistObraHito.fecha_acreditado)
        .join(ChecklistObraHito, ChecklistObraHito.checklist_id == ChecklistTecnico.id)
    )
    pagos: dict[tuple[str, str], dict[str, date | None]] = {}
    for programa, entidad_id, tipo, fecha in result.all():
        pagos.setdefault((programa, entidad_id), {})[tipo] = fecha

    con_anticipo = {k: v for k, v in pagos.items() if v.get("anticipo") is not None}
    ids: dict[str, set[str]] = {}
    for programa, entidad_id in con_anticipo:
        ids.setdefault(programa, set()).add(entidad_id)
    entidades = await _entidades(db, ids)

    filas = []
    for clave, p in con_anticipo.items():
        entidad = entidades.get(clave)
        if entidad is None:  # dada de baja
            continue
        fila = armar_fila(entidad, p)
        if fila is not None:
            filas.append(fila)
    return ordenar_filas(filas)


# ── Sincronización ──────────────────────────────────────────────────────────────

def _rango(celdas: str) -> str:
    tab = settings.gobabierto_sheet_tab.replace("'", "''")
    return f"'{tab}'!{celdas}"


async def sincronizar(db: AsyncSession, origen: str) -> int:
    """Reescribe la pestaña completa. Devuelve la cantidad de filas escritas.

    Siempre deja una fila en `viv_gobabierto_sync_log` y hace commit, también cuando falla
    (el caller convierte la excepción en un error HTTP, que haría rollback del log).
    """
    started_at = datetime.now(timezone.utc)
    log = GobAbiertoSyncLog(started_at=started_at, origen=origen)
    db.add(log)
    try:
        if not settings.gobabierto_sheet_id:
            raise GobAbiertoSyncError("GOBABIERTO_SHEET_ID no configurado")
        filas = await construir_filas(db)
        try:
            ultima = len(filas) + 1  # fila 1 = encabezados
            await google_sheets.update_and_clear(
                settings.gobabierto_sheet_id,
                [(_rango("B1:Q1"), [ENCABEZADOS])]
                + ([(_rango(f"B2:Q{ultima}"), filas)] if filas else []),
                _rango(f"B{ultima + 1}:Q"),
            )
        except Exception as exc:  # noqa: BLE001 — cualquier falla de Google es una falla de la corrida
            status = _status_http(exc)
            detalle = f"HTTP {status}: {exc}" if status else f"{type(exc).__name__}: {exc}"
            raise GobAbiertoSyncError(
                f"No se pudo escribir la planilla ({detalle})", es_permiso=status in (403, 404)
            ) from exc
    except GobAbiertoSyncError as exc:
        log.finished_at = datetime.now(timezone.utc)
        log.ok = False
        log.error = str(exc)[:2000]
        if origen == "scheduler":
            await notificaciones_service.crear(db, _SYNC_ACTOR, {
                "titulo": "Falló la exportación a la planilla de Gobierno Abierto",
                "mensaje": _mensaje_falla(exc),
                "nivel": "error",
                "origen": "gobabierto_sync",
                "destino_tipo": "rol",
                "destino_valor": "Admin",
            })
        await db.commit()
        raise

    log.finished_at = datetime.now(timezone.utc)
    log.ok = True
    log.filas = len(filas)
    await db.commit()
    return len(filas)


# ── Disparo inmediato desde el PATCH de hito ────────────────────────────────────
# Best-effort: corre como BackgroundTask, con su propia sesión (la del request ya cerró).
# Si llegan varias fechas mientras corre una sincronización, se juntan en una corrida más.

_session_factory: async_sessionmaker = AsyncSessionLocal
_lock = asyncio.Lock()
_pendiente = False


async def sincronizar_en_segundo_plano() -> None:
    global _pendiente
    if not settings.gobabierto_export_enabled:
        return
    _pendiente = True
    if _lock.locked():
        return  # la corrida en curso vuelve a correr al terminar
    async with _lock:
        while _pendiente:
            _pendiente = False
            try:
                async with _session_factory() as db:
                    await sincronizar(db, origen="hito")
            except Exception:  # noqa: BLE001 — nunca afecta al PATCH; queda en el log
                logger.exception("gobabierto: falló la sincronización disparada por un hito")
