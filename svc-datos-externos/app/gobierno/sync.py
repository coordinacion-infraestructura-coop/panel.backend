"""Sincronización de solo lectura del nomenclador de localidades de Gobierno
y de la vista por localidad ("0. Resumen General - Vista").

Ver spec: docs/files/spec-datos-externos-fase1-nomenclador-demografia.md §5.

Dos lecturas, con distinta tolerancia:
- Nomenclador: si falla la lectura, faltan encabezados o vienen menos de
  `_MIN_GOBIERNOS_LOCALES` filas, la corrida falla entera sin tocar datos.
- Vista: si falla, el nomenclador ya sincronizado se conserva y la corrida
  queda `parcial`.

Desde la v1.2.0 del spec la ficha sale de la Vista y no de la pestaña
`DATOS LOC` de "0. Resumen General", que el área no puede compartir. La Vista
trae menos columnas: superficie, población 2010, electores, empleados, masa
salarial, intendente, reelecto, continuidad, legislador y contacto quedan sin
fuente (las columnas siguen en el modelo, en `NULL`).

Regla de privacidad: ni `anomalias` ni los logs de aplicación llevan valores
de campos restringidos — sólo el código de la localidad y el nombre del campo.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.geo_censo.models import ExtGeoCenso
from app.gobierno.models import ExtGobEnte, ExtGobLocalidad, ExtGobSyncLog
from app.gobierno.schemas import GobSyncFuenteResponse, GobSyncResultResponse
from app.integrations import geo_resolver, google_sheets

logger = logging.getLogger(__name__)

FUENTE_NOMENCLADOR = "nomenclador"
FUENTE_VISTA = "resumen_vista"

_RANGO_NOMENCLADOR = "LOCALIDADES!A1:Z"
# Sin nombre de pestaña: la Vista tiene una sola ("Hoja 1") y así un cambio de
# nombre no rompe la lectura.
_RANGO_VISTA = "A1:AZ"

# Fila (0-based) donde están los encabezados de cada pestaña: el nomenclador
# tiene un título en la fila 1.
_FILA_ENCABEZADOS_NOMENCLADOR = 1
_FILA_ENCABEZADOS_VISTA = 0

# Freno de seguridad: una planilla vaciada o mal filtrada no debe dar de
# baja el padrón (hoy son 427 gobiernos locales).
_MIN_GOBIERNOS_LOCALES = 400

_COLS_NOMENCLADOR = ("ID_LOC", "LOCALIDADES", "ID_DPTO", "DEPARTAMENTOS", "ID_COPA", "TIPO")

# Lista blanca de la Vista: encabezado de la planilla -> (campo, tipo).
# Una columna nueva en la planilla no entra al sistema hasta sumarla acá (y
# al spec); una columna esperada que falta hace fallar esta lectura. Las
# columnas de montos de la Vista (ATP, COPA, FOFINDES, etc.) quedan fuera a
# propósito (spec §3.2).
_COLS_VISTA: dict[str, tuple[str, str]] = {
    "POBLACION": ("poblacion_2022_gob", "entero"),
    "PARTIDO": ("partido", "texto"),
}

_LARGO_TEXTO = 150
_LARGO_CONTACTO = 40

_ZONA_RURAL_RE = re.compile(r"^\d+ZR$")


class SyncFallido(Exception):
    """La corrida no pudo arrancar (lectura del nomenclador, estructura o
    freno de seguridad). No se tocó ningún dato."""


class _LecturaInvalida(Exception):
    pass


# ── Helpers de parseo ─────────────────────────────────────────────────────────

def _norm_header(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw if raw is not None else "")).strip().upper()


def _clean_str(raw: Any) -> str | None:
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    return s or None


def normalizar_codigo(raw: Any) -> str | None:
    """`142007`, `142007.0`, `"142.007"`, `"142,007"` -> `"142007"`;
    `"1zr"` -> `"1ZR"`. Cualquier otra cosa (vacío, `#N/A`) -> `None`."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return str(int(raw)) if float(raw).is_integer() and raw > 0 else None
    s = str(raw).strip().upper().replace(" ", "")
    if not s:
        return None
    if _ZONA_RURAL_RE.match(s):
        return s
    solo_digitos = s.replace(".", "").replace(",", "")
    return solo_digitos if solo_digitos.isdigit() else None


def clasificar_fila(codigo: str | None, tipo: str | None) -> str | None:
    """`"local"` | `"comunidad_regional"` | `"zona_rural"` | `None` (inválida)."""
    if not codigo:
        return None
    if _ZONA_RURAL_RE.match(codigo):
        return "zona_rural"
    if tipo in ("MU", "CO"):
        return "local" if len(codigo) == 6 else None
    if not tipo and len(codigo) <= 4:
        return "comunidad_regional"
    return None


def _parse_numero(raw: Any) -> tuple[float | None, bool]:
    """Devuelve `(valor, invalido)`. Vacío -> `(None, False)`; no numérico o
    negativo -> `(None, True)`."""
    if raw is None or raw == "":
        return None, False
    if isinstance(raw, bool):
        return None, True
    if isinstance(raw, (int, float)):
        valor = float(raw)
    else:
        s = str(raw).strip().replace("$", "").replace(" ", "")
        if not s:
            return None, False
        try:
            valor = float(s)
        except ValueError:
            try:
                valor = float(s.replace(".", "").replace(",", "."))
            except ValueError:
                return None, True
    if valor != valor or valor < 0:  # NaN o negativo
        return None, True
    return valor, False


def _parse_si_no(raw: Any) -> tuple[bool | None, bool]:
    s = _clean_str(raw)
    if s is None:
        return None, False
    s = s.upper()
    if s in ("SI", "SÍ"):
        return True, False
    if s == "NO":
        return False, False
    return None, True


def _parse_contacto(raw: Any) -> tuple[str | None, bool]:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        s = str(int(raw)) if float(raw).is_integer() else str(raw)
    else:
        s = _clean_str(raw)
    if s is None:
        return None, False
    if len(s) > _LARGO_CONTACTO:
        return None, True
    return s, False


def _convertir(raw: Any, tipo: str) -> tuple[Any, bool]:
    if tipo == "entero":
        valor, invalido = _parse_numero(raw)
        return (int(round(valor)) if valor is not None else None), invalido
    if tipo == "decimal":
        return _parse_numero(raw)
    if tipo == "si_no":
        return _parse_si_no(raw)
    if tipo == "contacto":
        return _parse_contacto(raw)
    s = _clean_str(raw)
    return (s[:_LARGO_TEXTO] if s else None), False


def _indices(valores: list[list[Any]], fila_encabezados: int, esperados: tuple[str, ...] | list[str]) -> dict[str, int]:
    """Posición de cada encabezado esperado, buscado por nombre (no por
    posición). Lanza `_LecturaInvalida` si falta alguno."""
    if len(valores) <= fila_encabezados:
        raise _LecturaInvalida("la pestaña no tiene fila de encabezados")
    encabezados = [_norm_header(h) for h in valores[fila_encabezados]]
    idx: dict[str, int] = {}
    faltantes = []
    for nombre in esperados:
        if nombre in encabezados:
            idx[nombre] = encabezados.index(nombre)
        else:
            faltantes.append(nombre)
    if faltantes:
        raise _LecturaInvalida(f"faltan encabezados: {', '.join(faltantes)}")
    return idx


def _celda(fila: list[Any], i: int) -> Any:
    return fila[i] if i < len(fila) else None


# ── Lectura y clasificación del nomenclador ───────────────────────────────────

def parsear_nomenclador(valores: list[list[Any]]) -> tuple[list[dict], list[dict], list[dict]]:
    """Devuelve `(gobiernos_locales, entes, anomalias)`."""
    idx = _indices(valores, _FILA_ENCABEZADOS_NOMENCLADOR, _COLS_NOMENCLADOR)
    locales: list[dict] = []
    entes: list[dict] = []
    anomalias: list[dict] = []
    vistos: set[str] = set()

    for n, fila in enumerate(valores[_FILA_ENCABEZADOS_NOMENCLADOR + 1:], start=_FILA_ENCABEZADOS_NOMENCLADOR + 2):
        if not any(c not in (None, "") for c in fila):
            continue
        codigo = normalizar_codigo(_celda(fila, idx["ID_LOC"]))
        tipo = (_clean_str(_celda(fila, idx["TIPO"])) or "").upper() or None
        clase = clasificar_fila(codigo, tipo)
        nombre = _clean_str(_celda(fila, idx["LOCALIDADES"]))
        if clase is None or not nombre:
            anomalias.append({"tipo": "fila_invalida", "fila": n})
            continue
        if codigo in vistos:
            anomalias.append({"tipo": "codigo_duplicado", "codigo": codigo, "fila": n})
            continue
        vistos.add(codigo)
        departamento = _clean_str(_celda(fila, idx["DEPARTAMENTOS"]))
        if clase == "local":
            id_copa, _ = _parse_numero(_celda(fila, idx["ID_COPA"]))
            locales.append({
                "codigo_indec": codigo,
                "nombre_gob": nombre[:_LARGO_TEXTO],
                "departamento_gob": (departamento or "")[:100],
                "codigo_dpto_indec": normalizar_codigo(_celda(fila, idx["ID_DPTO"])),
                "id_copa": int(id_copa) if id_copa is not None else None,
                "tipo": tipo,
            })
        else:
            entes.append({
                "codigo": codigo,
                "nombre": nombre[:_LARGO_TEXTO],
                "tipo_ente": clase,
                "departamento": departamento[:100] if departamento else None,
            })
    return locales, entes, anomalias


# ── Persistencia ──────────────────────────────────────────────────────────────

async def _guardar_log(
    db: AsyncSession,
    fuente: str,
    estado: str,
    disparado_por: str,
    anomalias: list[dict],
    leidas: int = 0,
    upsert: int = 0,
    error: int = 0,
    sin_match: int = 0,
) -> ExtGobSyncLog:
    log = ExtGobSyncLog(
        fuente=fuente,
        filas_leidas=leidas,
        filas_upsert=upsert,
        filas_error=error,
        filas_sin_match=sin_match,
        anomalias=anomalias,
        estado=estado,
        corrida_en=datetime.now(timezone.utc),
        disparado_por=disparado_por,
    )
    db.add(log)
    await db.flush()
    return log


async def _fallar(db: AsyncSession, disparado_por: str, motivo: str) -> None:
    """Deja registrada la corrida fallida y lanza `SyncFallido`. El commit es
    explícito: el router traduce la excepción a un 502 y `get_db` hace
    rollback, lo que se llevaría puesto el log."""
    await _guardar_log(
        db, FUENTE_NOMENCLADOR, "fallido", disparado_por, [{"tipo": "corrida_fallida", "detalle": motivo}]
    )
    await db.commit()
    raise SyncFallido(motivo)


async def _upsert_nomenclador(
    db: AsyncSession, locales: list[dict], entes: list[dict], anomalias: list[dict]
) -> tuple[int, int, int]:
    """Devuelve `(upsert, error, sin_id_geo)`."""
    pares = [(f["departamento_gob"], f["nombre_gob"]) for f in locales]
    resueltos = await geo_resolver.resolver_localidades(pares, [1] * len(pares))
    # Resolver caído o apagado devuelve todo `(None, None)`: en ese caso no
    # se pisa un `id_geo` resuelto en una corrida anterior.
    resolver_respondio = any(id_geo for id_geo, _ in resueltos)

    existentes = {r.codigo_indec: r for r in (await db.execute(select(ExtGobLocalidad))).scalars().all()}
    ahora = datetime.now(timezone.utc)
    upsert = error = 0

    for f, (id_geo, match_tipo) in zip(locales, resueltos):
        try:
            # SAVEPOINT por fila — una fila mala no frena el lote.
            async with db.begin_nested():
                loc = existentes.get(f["codigo_indec"])
                if loc is None:
                    loc = ExtGobLocalidad(codigo_indec=f["codigo_indec"])
                    db.add(loc)
                loc.nombre_gob = f["nombre_gob"]
                loc.departamento_gob = f["departamento_gob"]
                loc.codigo_dpto_indec = f["codigo_dpto_indec"]
                loc.id_copa = f["id_copa"]
                loc.tipo = f["tipo"]
                if resolver_respondio:
                    loc.id_geo = id_geo
                    loc.match_tipo = match_tipo
                loc.deleted_at = None
                loc.updated_at = ahora
                await db.flush()
            upsert += 1
        except Exception as exc:  # noqa: BLE001 — una fila con error no frena el resto
            error += 1
            anomalias.append({"tipo": "error_fila", "codigo": f["codigo_indec"], "detalle": type(exc).__name__})

    codigos = {f["codigo_indec"] for f in locales}
    for codigo, loc in existentes.items():
        if codigo not in codigos and loc.deleted_at is None:
            loc.deleted_at = ahora
            anomalias.append({"tipo": "baja", "codigo": codigo})

    entes_existentes = {e.codigo: e for e in (await db.execute(select(ExtGobEnte))).scalars().all()}
    for f in entes:
        try:
            async with db.begin_nested():
                ente = entes_existentes.get(f["codigo"])
                if ente is None:
                    ente = ExtGobEnte(codigo=f["codigo"])
                    db.add(ente)
                ente.nombre = f["nombre"]
                ente.tipo_ente = f["tipo_ente"]
                ente.departamento = f["departamento"]
                ente.deleted_at = None
                ente.updated_at = ahora
                await db.flush()
            upsert += 1
        except Exception as exc:  # noqa: BLE001
            error += 1
            anomalias.append({"tipo": "error_fila", "codigo": f["codigo"], "detalle": type(exc).__name__})

    codigos_entes = {f["codigo"] for f in entes}
    for codigo, ente in entes_existentes.items():
        if codigo not in codigos_entes and ente.deleted_at is None:
            ente.deleted_at = ahora
            anomalias.append({"tipo": "baja", "codigo": codigo})
    await db.flush()

    sin_id_geo = len(
        (await db.execute(
            select(ExtGobLocalidad.codigo_indec).where(
                ExtGobLocalidad.deleted_at.is_(None), ExtGobLocalidad.id_geo.is_(None)
            )
        )).all()
    )
    return upsert, error, sin_id_geo


async def _aplicar_vista(db: AsyncSession, valores: list[list[Any]], anomalias: list[dict]) -> tuple[int, int, int, int]:
    """Devuelve `(leidas, upsert, error, sin_match)`."""
    idx = _indices(valores, _FILA_ENCABEZADOS_VISTA, ["ID_LOC", *_COLS_VISTA])

    # Se vuelven a traer: un SAVEPOINT revertido en el paso anterior deja las
    # instancias expiradas, y en async no hay carga perezosa.
    locales = {
        r.codigo_indec: r
        for r in (await db.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars().all()
    }
    entes = {
        e.codigo: e
        for e in (await db.execute(select(ExtGobEnte).where(ExtGobEnte.deleted_at.is_(None)))).scalars().all()
    }
    ahora = datetime.now(timezone.utc)
    leidas = upsert = error = sin_match = 0

    for fila in valores[_FILA_ENCABEZADOS_VISTA + 1:]:
        codigo = normalizar_codigo(_celda(fila, idx["ID_LOC"]))
        if codigo is None:
            continue  # filas de total o de relleno
        leidas += 1

        convertidos: dict[str, Any] = {}
        for encabezado, (campo, tipo) in _COLS_VISTA.items():
            valor, invalido = _convertir(_celda(fila, idx[encabezado]), tipo)
            convertidos[campo] = valor
            if invalido:
                # Sólo código y campo: nunca el valor (puede ser restringido).
                anomalias.append({"tipo": "valor_invalido", "codigo": codigo, "campo": campo})

        try:
            async with db.begin_nested():
                if codigo in locales:
                    loc = locales[codigo]
                    for campo, valor in convertidos.items():
                        setattr(loc, campo, valor)
                    loc.updated_at = ahora
                elif codigo in entes and entes[codigo].tipo_ente == "zona_rural":
                    # Hoy la Vista no trae zonas rurales; si vuelven, sólo
                    # traen población 2022 (no hay 2010).
                    ente = entes[codigo]
                    ente.poblacion_2022 = convertidos["poblacion_2022_gob"]
                    ente.updated_at = ahora
                else:
                    sin_match += 1
                    anomalias.append({"tipo": "codigo_fuera_del_nomenclador", "codigo": codigo})
                    continue
                await db.flush()
            upsert += 1
        except Exception as exc:  # noqa: BLE001
            error += 1
            anomalias.append({"tipo": "error_fila", "codigo": codigo, "detalle": type(exc).__name__})

    return leidas, upsert, error, sin_match


async def _cerrar_censo(db: AsyncSession, anomalias: list[dict]) -> int:
    """Completa el `id_geo` de las filas del Censo que quedaron sin resolver
    (el Cuadro 1.6 no trae departamento; el nomenclador sí). Nunca pisa un
    `id_geo` ya resuelto. También deja las anomalías de control cruzado."""
    locales = {
        r.codigo_indec: r
        for r in (await db.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars().all()
    }
    censo = (await db.execute(select(ExtGeoCenso).where(ExtGeoCenso.deleted_at.is_(None)))).scalars().all()
    ids_en_uso = {c.id_geo for c in censo if c.id_geo}
    cerrados = 0

    for c in censo:
        loc = locales.get(c.codigo_indec)
        if loc is None:
            anomalias.append({"tipo": "censo_sin_nomenclador", "codigo": c.codigo_indec})
            continue
        if c.id_geo is None and loc.id_geo:
            if loc.id_geo in ids_en_uso:
                anomalias.append({"tipo": "censo_id_geo_en_conflicto", "codigo": c.codigo_indec})
            else:
                c.id_geo = loc.id_geo
                c.departamento_censo = loc.departamento_gob
                c.match_tipo = "nomenclador_gob"
                ids_en_uso.add(loc.id_geo)
                cerrados += 1
        if (
            loc.poblacion_2022_gob is not None
            and c.poblacion_2022 is not None
            and loc.poblacion_2022_gob != c.poblacion_2022
        ):
            anomalias.append({"tipo": "poblacion_difiere_del_censo", "codigo": c.codigo_indec})

    codigos_censo = {c.codigo_indec for c in censo}
    for codigo in locales:
        if codigo not in codigos_censo:
            anomalias.append({"tipo": "nomenclador_sin_censo", "codigo": codigo})
    await db.flush()
    return cerrados


# ── Orquestación ──────────────────────────────────────────────────────────────

async def sync_localidades(db: AsyncSession, disparado_por: str = "cloud-scheduler") -> GobSyncResultResponse:
    if not settings.google_sheet_gob_nomenclador_id:
        raise SyncFallido("GOOGLE_SHEET_GOB_NOMENCLADOR_ID no está configurado")

    try:
        valores = await google_sheets.get_values(
            settings.google_sheet_gob_nomenclador_id, _RANGO_NOMENCLADOR, "UNFORMATTED_VALUE"
        )
    except Exception as exc:  # noqa: BLE001 — cualquier falla de la fuente externa
        await _fallar(db, disparado_por, f"No se pudo leer el nomenclador: {type(exc).__name__}")

    try:
        locales, entes, anomalias_nom = parsear_nomenclador(valores)
    except _LecturaInvalida as exc:
        await _fallar(db, disparado_por, f"Nomenclador con estructura inesperada: {exc}")

    if len(locales) < _MIN_GOBIERNOS_LOCALES:
        await _fallar(
            db,
            disparado_por,
            f"El nomenclador trae {len(locales)} gobiernos locales (mínimo {_MIN_GOBIERNOS_LOCALES}); no se tocó ningún dato",
        )

    upsert, error, sin_id_geo = await _upsert_nomenclador(db, locales, entes, anomalias_nom)

    # ── Vista: si falla, se conserva el nomenclador y la corrida queda parcial
    anomalias_loc: list[dict] = []
    estado_loc = "ok"
    leidas_loc = upsert_loc = error_loc = sin_match_loc = 0
    try:
        if not settings.google_sheet_gob_resumen_vista_id:
            raise _LecturaInvalida("GOOGLE_SHEET_GOB_RESUMEN_VISTA_ID no está configurado")
        try:
            valores_loc = await google_sheets.get_values(
                settings.google_sheet_gob_resumen_vista_id, _RANGO_VISTA, "UNFORMATTED_VALUE"
            )
        except Exception as exc:  # noqa: BLE001
            raise _LecturaInvalida(f"no se pudo leer la planilla: {type(exc).__name__}") from exc
        leidas_loc, upsert_loc, error_loc, sin_match_loc = await _aplicar_vista(db, valores_loc, anomalias_loc)
        if error_loc:
            estado_loc = "parcial"
    except _LecturaInvalida as exc:
        estado_loc = "fallido"
        anomalias_loc.append({"tipo": "lectura_fallida", "detalle": str(exc)})
        logger.warning("sync gobierno: la Vista no se pudo aplicar: %s", exc)

    censo_cerrados = await _cerrar_censo(db, anomalias_nom)

    estado_nom = "parcial" if error else "ok"
    log_nom = await _guardar_log(
        db, FUENTE_NOMENCLADOR, estado_nom, disparado_por, anomalias_nom,
        leidas=len(locales) + len(entes), upsert=upsert, error=error, sin_match=sin_id_geo,
    )
    log_loc = await _guardar_log(
        db, FUENTE_VISTA, estado_loc, disparado_por, anomalias_loc,
        leidas=leidas_loc, upsert=upsert_loc, error=error_loc, sin_match=sin_match_loc,
    )

    return GobSyncResultResponse(
        estado="ok" if estado_nom == "ok" and estado_loc == "ok" else "parcial",
        gobiernos_locales=len(locales),
        entes=len(entes),
        con_id_geo=len(locales) - sin_id_geo,
        sin_id_geo=sin_id_geo,
        censo_cerrados=censo_cerrados,
        fuentes=[GobSyncFuenteResponse.model_validate(log_nom), GobSyncFuenteResponse.model_validate(log_loc)],
    )


async def get_sync_estado(db: AsyncSession) -> list[ExtGobSyncLog]:
    """Última corrida de cada fuente."""
    resultado = []
    for fuente in (FUENTE_NOMENCLADOR, FUENTE_VISTA):
        log = (
            await db.execute(
                select(ExtGobSyncLog)
                .where(ExtGobSyncLog.fuente == fuente)
                .order_by(ExtGobSyncLog.corrida_en.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if log:
            resultado.append(log)
    return resultado
