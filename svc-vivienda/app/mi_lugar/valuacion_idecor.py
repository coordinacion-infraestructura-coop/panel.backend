"""Valor fiscal sugerido y valor de referencia de mercado desde IDECOR
(docs/files/spec-mi-lugar-valor-fiscal-idecor.md, ADR-031).

La consulta a IDECOR la hace svc-datos-externos (`POST
/internal/datos-externos/catastro/valuacion`, IAM-only); acá solo se le pasan
los puntos y nomenclaturas del proyecto y se guarda la respuesta en
`viv_ml_valuacion_idecor`. Nada de este módulo escribe en
`ProyectoML.valor_fiscal`: ese campo sigue siendo de carga manual.

Fail-open: un error de red o de la fuente nunca hace fallar el alta o la
edición de un proyecto, y no pisa el último resultado bueno (§5.3).
"""
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.mi_lugar.models import GeoPuntoML, NomenclaturaML, ProyectoML, ValuacionIdecorML
from app.mi_lugar.schemas import ValuacionIdecorOut

logger = logging.getLogger(__name__)

# Estados que guardan un resultado bueno de IDECOR (aunque sea incompleto).
_ESTADOS_CON_RESULTADO = ("ok", "parcial", "sin_parcelas")


class ValuacionNoDisponible(Exception):
    """svc-datos-externos o IDECOR no respondieron con un resultado usable."""


def habilitada() -> bool:
    return settings.valuacion_idecor_enabled and bool(settings.svc_datos_externos_internal_url)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mint_id_token(audience: str) -> str | None:
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token

        return id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    except Exception as exc:  # noqa: BLE001 — sin credenciales (local/test) es esperable
        logger.warning("valuacion_idecor: no se pudo mintear ID token: %s", exc)
        return None


async def consultar_datos_externos(puntos: list[dict], nomenclaturas: list[str]) -> dict:
    base = settings.svc_datos_externos_internal_url.rstrip("/")
    url = base + settings.datos_externos_valuacion_internal_path
    token = _mint_id_token(base)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json={"puntos": puntos, "nomenclaturas": nomenclaturas}, headers=headers)
    except httpx.HTTPError as exc:
        raise ValuacionNoDisponible(f"svc-datos-externos no respondió: {exc!r}") from exc
    if resp.status_code != 200:
        raise ValuacionNoDisponible(f"svc-datos-externos respondió {resp.status_code}: {(resp.text or '')[:500]}")
    return resp.json()


def _dec(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def _aplicar_resultado(fila: ValuacionIdecorML, r: dict) -> None:
    parcelas = r.get("parcelas") or []
    no_encontradas = r.get("nomenclaturas_no_encontradas") or []
    puntos_sin_parcela = len(r.get("puntos_sin_parcela") or [])
    if not parcelas:
        fila.estado = "sin_parcelas"
    elif no_encontradas or puntos_sin_parcela:
        fila.estado = "parcial"
    else:
        fila.estado = "ok"
    fila.valor_total = _dec(r.get("valor_total")) if parcelas else None
    fila.valor_tierra = _dec(r.get("valor_tierra")) if parcelas else None
    fila.valor_mejoras = _dec(r.get("valor_mejoras")) if parcelas else None
    fila.valor_mercado = _dec(r.get("valor_mercado"))
    fila.mercado_anio = r.get("mercado_anio")
    fila.mercado_parcelas_sin_valor = r.get("mercado_parcelas_sin_valor") or 0
    fila.cant_parcelas = len(parcelas)
    fila.puntos_sin_parcela = puntos_sin_parcela
    fila.nomenclaturas_no_encontradas = json.dumps(no_encontradas)
    vigencia = r.get("vigencia_desde")
    fila.vigencia_desde = date.fromisoformat(vigencia) if vigencia else None
    fila.parcelas = json.dumps(parcelas, default=str)
    fila.consultado_at = _now()
    fila.ultimo_error = None
    fila.ultimo_error_at = None


def _limpiar_resultado(fila: ValuacionIdecorML, estado: str) -> None:
    fila.estado = estado
    fila.valor_total = fila.valor_tierra = fila.valor_mejoras = fila.valor_mercado = None
    fila.mercado_anio = fila.vigencia_desde = None
    fila.mercado_parcelas_sin_valor = fila.cant_parcelas = fila.puntos_sin_parcela = 0
    fila.nomenclaturas_no_encontradas = "[]"
    fila.parcelas = "[]"


async def recalcular(db: AsyncSession, proyecto_id: str) -> ValuacionIdecorML:
    """Consulta y guarda (sin commit). Nunca lanza por fallas de la fuente: las
    registra en `ultimo_error` y conserva el último resultado bueno."""
    puntos = (await db.execute(
        select(GeoPuntoML).where(GeoPuntoML.proyecto_id == proyecto_id).order_by(GeoPuntoML.orden)
    )).scalars().all()
    nomenclaturas = (await db.execute(
        select(NomenclaturaML.nomenclatura)
        .where(NomenclaturaML.proyecto_id == proyecto_id, NomenclaturaML.deleted_at.is_(None))
        .order_by(NomenclaturaML.created_at)
    )).scalars().all()

    fila = await db.get(ValuacionIdecorML, proyecto_id)
    if fila is None:
        fila = ValuacionIdecorML(proyecto_id=proyecto_id, estado="sin_datos")
        db.add(fila)

    if not puntos and not nomenclaturas:
        _limpiar_resultado(fila, "sin_datos")
        fila.consultado_at = _now()
        fila.ultimo_error = fila.ultimo_error_at = None
        await db.flush()
        return fila

    try:
        resultado = await consultar_datos_externos(
            [{"lat": float(p.lat), "lng": float(p.lng)} for p in puntos], list(nomenclaturas)
        )
        _aplicar_resultado(fila, resultado)
    except Exception as exc:  # noqa: BLE001 — fail-open (spec §5.3)
        logger.warning("valuacion_idecor: falló la consulta del proyecto %s: %r", proyecto_id, exc)
        fila.ultimo_error = str(exc)[:2000]
        fila.ultimo_error_at = _now()
        if fila.estado not in _ESTADOS_CON_RESULTADO:
            _limpiar_resultado(fila, "error")
    await db.flush()
    return fila


async def recalcular_en_segundo_plano(proyecto_id: str) -> None:
    """Para `BackgroundTasks` después del alta/edición: corre con su propia
    sesión, una vez que la transacción del request ya hizo commit."""
    if not habilitada():
        return
    try:
        async with AsyncSessionLocal() as db:
            await recalcular(db, proyecto_id)
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — nunca debe romper nada
        logger.warning("valuacion_idecor: tarea en segundo plano falló para %s: %r", proyecto_id, exc)


async def recalcular_todos(db: AsyncSession) -> dict:
    """Cloud Scheduler semanal: todos los proyectos `exp` no borrados. Cada
    proyecto va en su SAVEPOINT para que uno roto no arrastre a los demás."""
    ids = (await db.execute(
        select(ProyectoML.id).where(ProyectoML.tipo == "exp", ProyectoML.deleted_at.is_(None))
        .order_by(ProyectoML.created_at)
    )).scalars().all()
    por_estado: dict[str, int] = {}
    con_error = 0
    for proyecto_id in ids:
        async with db.begin_nested():
            fila = await recalcular(db, proyecto_id)
        por_estado[fila.estado] = por_estado.get(fila.estado, 0) + 1
        if fila.ultimo_error_at is not None:
            con_error += 1
    return {"proyectos": len(ids), "por_estado": por_estado, "con_error_en_esta_corrida": con_error}


def a_salida(fila: ValuacionIdecorML | None) -> ValuacionIdecorOut | None:
    if fila is None:
        return None
    return ValuacionIdecorOut(
        estado=fila.estado,
        valor_total=fila.valor_total,
        valor_tierra=fila.valor_tierra,
        valor_mejoras=fila.valor_mejoras,
        valor_mercado=fila.valor_mercado,
        mercado_anio=fila.mercado_anio,
        mercado_parcelas_sin_valor=fila.mercado_parcelas_sin_valor or 0,
        cant_parcelas=fila.cant_parcelas or 0,
        puntos_sin_parcela=fila.puntos_sin_parcela or 0,
        nomenclaturas_no_encontradas=json.loads(fila.nomenclaturas_no_encontradas or "[]"),
        vigencia_desde=fila.vigencia_desde,
        parcelas=json.loads(fila.parcelas or "[]"),
        consultado_at=fila.consultado_at,
        ultimo_error_at=fila.ultimo_error_at,
    )
