"""Sincronización de solo lectura de las planillas de transferencias de Gobierno
(spec-datos-externos-fase2-transferencias.md §3).

Cada fuente se aplica sola y por reemplazo completo dentro de un SAVEPOINT: se borra la tabla y
se inserta en bloque lo que viene de la planilla, ya validado en `parse.py`. Es distinto del
SAVEPOINT por fila de la Fase 1, y a propósito: son ~60.000 filas y el reemplazo atómico evita
mezclar dos versiones de la planilla. Si una fuente falla (lectura, estructura o freno de
seguridad) su tabla queda como estaba y las demás siguen.

Solo se leen las pestañas nombradas en `FUENTES`. Las pestañas con datos políticos o
personales de esas planillas (FODEMEP: `INFORME AUGUSTO`, `Copia de RESULTADOS CALVO`;
EMPLEADOS: `Búsqueda`) nunca se piden (spec §0).

Regla de privacidad: ni `anomalias` ni los logs llevan valores de empleados o masa salarial.

Fase 3 (spec-datos-externos-fase3-fondos.md §3): las planillas de fondos se suman como fuentes
de este mismo sync. Sus pestañas tienen columnas de personas (`INTENDENTE`, `CUIT`,
`OBSERVACIONES`); con `excluir=True` se lee primero el encabezado y después solo los rangos de
columnas que no lo son, así que esos datos nunca llegan al servicio.

Fase 5 (spec-datos-externos-fase5-gestion-territorial.md §3): obras, recorridos, reuniones y
convenios se suman igual. `excluir` también acepta la lista de columnas propia de la pestaña
(intendente y partido, detalle de reuniones, tema e institución de las visitas).

Fase 6 (spec-datos-externos-fase6-politico.md §3): el padrón de intendentes y la planilla de
elecciones. Algunas pestañas pegadas tienen una fila de títulos arriba del encabezado
(`fila_encabezado = 2`). Las que nombran la localidad en vez de traer el código se resuelven
contra el nomenclador después de guardarse (`_resolver_por_nombre`). Ni los logs ni `anomalias`
llevan nombres de personas, partidos por localidad ni teléfonos.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gob_fondos import parse as parse_fondos
from app.gob_gestion import parse as parse_gestion
from app.gob_politico import parse as parse_politico
from app.gob_politico.models import (
    ExtGobCircuitoLocalidad,
    ExtGobEleccionCircuito,
    ExtGobEleccionCopia,
    ExtGobEleccionMunicipal,
    ExtGobIntendente,
)
from app.gob_gestion.models import ExtGobConvenio, ExtGobObra, ExtGobReunion, ExtGobVisita, ExtGobVisitaGobernador
from app.gob_fondos.models import (
    ExtGobCregCuota,
    ExtGobFondoAmbiental,
    ExtGobFondoValor,
    ExtGobFpermEtapa,
    ExtGobFpermLocalidad,
    ExtGobFpermPrestamo,
)
from app.gob_transferencias import conciliacion, parse
from app.gob_transferencias.models import (
    ExtGobCopa,
    ExtGobEmpleados,
    ExtGobFodemep,
    ExtGobFodemepEstado,
    ExtGobFofindes,
    ExtGobFommep,
)
from app.gobierno.models import ExtGobEnte, ExtGobLocalidad, ExtGobSyncLog
from app.integrations import google_sheets

logger = logging.getLogger(__name__)

# Freno de seguridad (spec §3): una planilla vaciada o mal filtrada no debe borrar datos.
MIN_PROPORCION_FILAS = 0.9
MIN_LOCALIDADES = 400
_LOTE = 2000
_MAX_ANOMALIAS = 300


@dataclass(frozen=True)
class _Pestana:
    nombre: str
    parser: Callable[[list[list[Any]]], tuple[list[dict], list[dict]]]
    modelo: type
    # Freno de seguridad: "localidades" (Fase 2: mínimo de localidades y 90 % de las filas
    # previas), "proporcion" (90 % de las filas previas y al menos una) o "ninguno".
    freno: str = "localidades"
    # (columna, valor): la pestaña reemplaza solo esas filas del modelo (`ext_gob_fondo_valor`).
    alcance: tuple[str, str] | None = None
    # Saltear columnas al leer: True = las de personas de la Fase 3 (§3); una tupla = esos
    # encabezados (sin tildes, por prefijo), Fase 5 §3.
    excluir: bool | tuple[str, ...] = False
    # Fila del encabezado (1 = la primera). Las filas de arriba no llegan al parser.
    fila_encabezado: int = 1

    @property
    def excluidas(self) -> tuple[str, ...]:
        if self.excluir is True:
            return parse_fondos.COLUMNAS_SENSIBLES
        return self.excluir or ()


@dataclass(frozen=True)
class _Fuente:
    setting: str
    pestanas: tuple[_Pestana, ...]


FUENTES: dict[str, _Fuente] = {
    "copa": _Fuente("google_sheet_gob_copa_id", (_Pestana("COPA", parse.parsear_copa, ExtGobCopa),)),
    "fofindes": _Fuente("google_sheet_gob_fofindes_id", (_Pestana("FOFINDES", parse.parsear_fofindes, ExtGobFofindes),)),
    "fodemep": _Fuente(
        "google_sheet_gob_fodemep_id",
        (
            _Pestana("FODEMEP", parse.parsear_fodemep, ExtGobFodemep),
            _Pestana("ESTADO", parse.parsear_fodemep_estado, ExtGobFodemepEstado),
        ),
    ),
    "fommep": _Fuente("google_sheet_gob_fommep_id", (_Pestana("FROMMEP", parse.parsear_fommep, ExtGobFommep),)),
    "empleados": _Fuente("google_sheet_gob_empleados_id", (_Pestana("Activos MyC", parse.parsear_empleados, ExtGobEmpleados),)),
    # Fase 3. Las pestañas de Fondo Permanente forman una sola fuente: se aplican juntas.
    "fondo_permanente": _Fuente(
        "google_sheet_gob_fondo_permanente_id",
        (
            _Pestana("FONDO PERM", parse_fondos.parsear_fperm_localidad, ExtGobFpermLocalidad),
            _Pestana("FONDO PERM", parse_fondos.parsear_fperm_valores, ExtGobFondoValor, "ninguno", ("fondo", parse_fondos.FONDO_PERMANENTE)),
            # Las etapas disponibles bajan cuando se otorgan préstamos: sin freno por cantidad.
            _Pestana("FONDO PERM CUOTAS", parse_fondos.parsear_fperm_etapas, ExtGobFpermEtapa, "ninguno"),
            _Pestana("IMPORT_Listo", parse_fondos.parsear_fperm_prestamos, ExtGobFpermPrestamo, "proporcion", excluir=True),
        ),
    ),
    "fondo_ambiental": _Fuente(
        "google_sheet_gob_fondo_ambiental_id",
        (
            _Pestana("Fondo", parse_fondos.parsear_fondo_ambiental, ExtGobFondoAmbiental, "proporcion", excluir=True),
            _Pestana("Fondo", parse_fondos.parsear_fondo_ambiental_ingresos, ExtGobFondoValor, "ninguno",
                     ("fondo", parse_fondos.FONDO_AMBIENTAL), excluir=True),
        ),
    ),
    "comunidades_regionales": _Fuente(
        "google_sheet_gob_comunidades_regionales_id",
        (
            _Pestana("Fondo", parse_fondos.parsear_comunidades_regionales, ExtGobCregCuota, "proporcion", excluir=True),
            _Pestana("Control", parse_fondos.parsear_comunidades_regionales_credito, ExtGobFondoValor, "ninguno",
                     ("fondo", parse_fondos.COMUNIDADES_REGIONALES)),
        ),
    ),
    # Fase 5. Los recorridos de las dos planillas van a la misma tabla, separados por `origen`.
    "obras": _Fuente("google_sheet_gob_obras_id", (_Pestana("BD-TABLERO", parse_gestion.parsear_obras, ExtGobObra, "proporcion"),)),
    "recorridos": _Fuente(
        "google_sheet_gob_recorridos_id",
        (
            _Pestana("Recorrido", parse_gestion.parsear_recorrido(parse_gestion.ORIGEN_FUNCIONARIOS), ExtGobVisita, "proporcion",
                     ("origen", parse_gestion.ORIGEN_FUNCIONARIOS), excluir=parse_gestion.COLUMNAS_EXCLUIDAS["Recorrido"]),
            _Pestana("Visitas Gober", parse_gestion.parsear_visitas_gobernador, ExtGobVisitaGobernador,
                     excluir=parse_gestion.COLUMNAS_EXCLUIDAS["Visitas Gober"]),
        ),
    ),
    "recorridos_ministro": _Fuente(
        "google_sheet_gob_recorridos_ministro_id",
        (
            _Pestana("Recorrido", parse_gestion.parsear_recorrido(parse_gestion.ORIGEN_MINISTRO), ExtGobVisita, "proporcion",
                     ("origen", parse_gestion.ORIGEN_MINISTRO), excluir=parse_gestion.COLUMNAS_EXCLUIDAS["Recorrido"]),
        ),
    ),
    "reuniones": _Fuente(
        "google_sheet_gob_reuniones_id",
        (_Pestana("Reuniones", parse_gestion.parsear_reuniones, ExtGobReunion, "proporcion", excluir=parse_gestion.COLUMNAS_EXCLUIDAS["Reuniones"]),),
    ),
    "convenios": _Fuente("google_sheet_gob_convenios_id", (_Pestana("Convenios", parse_gestion.parsear_convenios, ExtGobConvenio),)),
    # Fase 6. El padrón está en la planilla de reuniones; es otra fuente para tener su propio log.
    "intendentes": _Fuente(
        "google_sheet_gob_reuniones_id",
        (_Pestana("Intendentes", parse_politico.parsear_intendentes, ExtGobIntendente, "proporcion"),),
    ),
    "elecciones": _Fuente(
        "google_sheet_gob_elecciones_id",
        (
            *(
                _Pestana(anio, parse_politico.parsear_circuitos(eleccion), ExtGobEleccionCircuito, "proporcion", ("eleccion", eleccion))
                for anio, eleccion in parse_politico.ELECCIONES.items()
            ),
            _Pestana("RESUMEN_VOTOS_CIRCUITOS", parse_politico.parsear_circuito_localidad, ExtGobCircuitoLocalidad, "proporcion",
                     excluir=parse_politico.COLUMNAS_EXCLUIDAS, fila_encabezado=2),
            _Pestana("Municipales - 2023", parse_politico.parsear_municipales, ExtGobEleccionMunicipal, "proporcion"),
            *(
                _Pestana(p, parse_politico.parsear_copia(p), ExtGobEleccionCopia, "proporcion", ("pestana", p),
                         excluir=parse_politico.COLUMNAS_EXCLUIDAS, fila_encabezado=2)
                for p in parse_politico.COPIAS
            ),
        ),
    ),
}

ETIQUETAS = {
    "copa": "11.1 Coparticipación (Gobierno)",
    "fofindes": "11.1 FOFINDES (Gobierno)",
    "fodemep": "11.1 FODEMEP (Gobierno)",
    "fommep": "11.1 FOMMEP (Gobierno)",
    "empleados": "13. Empleados (Gobierno)",
    "fondo_permanente": "7. Fondo Permanente (Gobierno)",
    "fondo_ambiental": "9. Fondo Ambiental (Gobierno)",
    "comunidades_regionales": "17. Comunidades Regionales (Gobierno)",
    "obras": "12. Obras (Gobierno)",
    "recorridos": "2. Recorrido y visitas (Gobierno)",
    "recorridos_ministro": "2.1 Recorrido y visitas del ministro (Gobierno)",
    "reuniones": "1. Registro de reuniones (Gobierno)",
    "convenios": "6. Convenios firmados (Gobierno)",
    "intendentes": "1. Registro de reuniones — Intendentes (Gobierno)",
    "elecciones": "18. Resultados elecciones 21-25 (Gobierno)",
}

_DESCARTES = {"fila_sin_codigo", "fila_invalida", "fila_repetida"}


async def _control_fondo_permanente(db: AsyncSession) -> list[dict]:
    """Localidades cuya suma de etapas disponibles no cierra con `FONDO PERM` (spec Fase 3 §3)."""
    suma = dict(
        (await db.execute(
            select(ExtGobFpermEtapa.codigo_indec, func.sum(ExtGobFpermEtapa.monto)).group_by(ExtGobFpermEtapa.codigo_indec)
        )).all()
    )
    distintas = [
        c for c, disponible in (await db.execute(select(ExtGobFpermLocalidad.codigo_indec, ExtGobFpermLocalidad.disponible))).all()
        if abs(float(disponible or 0) - float(suma.get(c) or 0)) >= 1
    ]
    return [{"tipo": "control_etapas_vs_disponible", "localidades": sorted(distintas)}] if distintas else []


async def _control_comunidades_regionales(db: AsyncSession) -> list[dict]:
    """Años y tipos donde las cuotas no anuladas superan el crédito vigente (spec Fase 3 §3)."""
    credito = {
        (anio, concepto): float(m or 0)
        for anio, concepto, m in (
            await db.execute(
                select(ExtGobFondoValor.anio, ExtGobFondoValor.concepto, ExtGobFondoValor.monto)
                .where(ExtGobFondoValor.fondo == parse_fondos.COMUNIDADES_REGIONALES)
            )
        ).all()
    }
    usado = (
        await db.execute(
            select(ExtGobCregCuota.anio, ExtGobCregCuota.tipo, func.sum(ExtGobCregCuota.monto_cuota))
            .where(func.coalesce(ExtGobCregCuota.estado, "") != "ANULADO")
            .group_by(ExtGobCregCuota.anio, ExtGobCregCuota.tipo)
        )
    ).all()
    excedidos = []
    for anio, tipo, total in usado:
        concepto = "credito_obras" if (tipo or "").lower().startswith("obra") else "credito_funcionamiento"
        if (anio, concepto) in credito and float(total or 0) > credito[(anio, concepto)] + 1:
            excedidos.append({"anio": anio, "tipo": tipo})
    return [{"tipo": "control_cuotas_sobre_credito", "casos": excedidos}] if excedidos else []


_CONTROLES_FONDOS = {
    "fondo_permanente": _control_fondo_permanente,
    "comunidades_regionales": _control_comunidades_regionales,
}


class SyncFallido(Exception):
    """Ninguna de las fuentes pedidas se pudo aplicar."""


class _FuenteFallida(Exception):
    pass


def _rango(pestana: str) -> str:
    return f"'{pestana}'!A1:CZ"


def _recortar(anomalias: list[dict]) -> list[dict]:
    if len(anomalias) <= _MAX_ANOMALIAS:
        return anomalias
    return anomalias[:_MAX_ANOMALIAS] + [{"tipo": "anomalias_recortadas", "total": len(anomalias)}]


def columna_a1(i: int) -> str:
    """0 -> `A`, 25 -> `Z`, 26 -> `AA`."""
    letras = ""
    i += 1
    while i:
        i, resto = divmod(i - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def rangos_sin_sensibles(
    pestana: str, encabezado: list[Any], excluidas: tuple[str, ...] = parse_fondos.COLUMNAS_SENSIBLES
) -> tuple[list[str], list[list[int]]]:
    """Rangos A1 de las columnas que no están excluidas, agrupadas en tramos contiguos, y las
    posiciones originales de cada tramo."""
    tramos: list[list[int]] = []
    for i, h in enumerate(encabezado):
        if parse_fondos.es_sensible(h, excluidas):
            continue
        if tramos and tramos[-1][-1] == i - 1:
            tramos[-1].append(i)
        else:
            tramos.append([i])
    return [f"'{pestana}'!{columna_a1(t[0])}1:{columna_a1(t[-1])}" for t in tramos], tramos


async def _leer_sin_sensibles(sheet_id: str, pestana: str, excluidas: tuple[str, ...], fila_encabezado: int = 1) -> list[list[Any]]:
    f = fila_encabezado
    encabezado = (await google_sheets.get_values(sheet_id, f"'{pestana}'!{f}:{f}", "UNFORMATTED_VALUE") or [[]])[0]
    rangos, tramos = rangos_sin_sensibles(pestana, encabezado, excluidas)
    if not rangos:
        return []
    partes = await google_sheets.batch_get_values(sheet_id, rangos, "UNFORMATTED_VALUE")
    alto = max((len(p) for p in partes), default=0)
    filas: list[list[Any]] = [[None] * len(encabezado) for _ in range(alto)]
    for parte, posiciones in zip(partes, tramos):
        for r, valores in enumerate(parte):
            for k, valor in enumerate(valores[: len(posiciones)]):
                filas[r][posiciones[k]] = valor
    # El encabezado se conserva completo: el parser ve las columnas sensibles, pero vacías.
    if len(filas) >= f:
        filas[f - 1] = list(encabezado)
    return filas


async def _leer(sheet_id: str, pestana: _Pestana) -> list[list[Any]]:
    try:
        if pestana.excluidas:
            return await _leer_sin_sensibles(sheet_id, pestana.nombre, pestana.excluidas, pestana.fila_encabezado)
        return await google_sheets.get_values(sheet_id, _rango(pestana.nombre), "UNFORMATTED_VALUE")
    except Exception as exc:  # noqa: BLE001 — cualquier falla de la fuente externa
        raise _FuenteFallida(f"no se pudo leer la pestaña {pestana.nombre}: {type(exc).__name__}") from exc


def _acotar(q, pestana: _Pestana):
    if pestana.alcance:
        columna, valor = pestana.alcance
        return q.where(getattr(pestana.modelo, columna) == valor)
    return q


async def _reemplazar(db: AsyncSession, pestana: _Pestana, filas: list[dict]) -> None:
    async with db.begin_nested():
        await db.execute(_acotar(delete(pestana.modelo), pestana))
        for i in range(0, len(filas), _LOTE):
            await db.execute(insert(pestana.modelo), filas[i : i + _LOTE])


def _frenar(pestana: _Pestana, filas: list[dict], previas: int) -> None:
    if pestana.freno == "ninguno":
        return
    if pestana.freno == "localidades":
        localidades = len({f["codigo_indec"] for f in filas})
        if localidades < MIN_LOCALIDADES:
            raise _FuenteFallida(
                f"la pestaña {pestana.nombre} trae {localidades} localidades (mínimo {MIN_LOCALIDADES}); no se tocó ningún dato"
            )
    elif not filas:
        raise _FuenteFallida(f"la pestaña {pestana.nombre} no trae filas; no se tocó ningún dato")
    if previas and len(filas) < previas * MIN_PROPORCION_FILAS:
        raise _FuenteFallida(
            f"la pestaña {pestana.nombre} trae {len(filas)} filas contra {previas} de la corrida anterior; no se tocó ningún dato"
        )


async def _aplicar(
    db: AsyncSession, fuente: str, codigos_nomenclador: set[str], entes: frozenset[str] | set[str] = frozenset()
) -> tuple[int, int, int, list[dict]]:
    """Lee, valida y reemplaza todas las pestañas de una fuente. Devuelve
    `(leidas, insertadas, descartadas, anomalias)`; lanza `_FuenteFallida` sin tocar datos."""
    definicion = FUENTES[fuente]
    sheet_id = getattr(settings, definicion.setting)
    if not sheet_id:
        raise _FuenteFallida(f"{definicion.setting.upper()} no está configurado")

    parseadas: list[tuple[_Pestana, list[dict]]] = []
    anomalias: list[dict] = []
    leidas = 0
    leidas_por_pestana: dict[str, list[list[Any]]] = {}
    for pestana in definicion.pestanas:
        # Una pestaña que alimenta dos tablas (p. ej. `Fondo` y sus ingresos) se lee una vez.
        if pestana.nombre not in leidas_por_pestana:
            leidas_por_pestana[pestana.nombre] = await _leer(sheet_id, pestana)
            leidas += max(len(leidas_por_pestana[pestana.nombre]) - 1, 0)
        valores = leidas_por_pestana[pestana.nombre][pestana.fila_encabezado - 1:]
        try:
            filas, anom = pestana.parser(valores)
        except parse.EstructuraInvalida as exc:
            raise _FuenteFallida(f"pestaña {pestana.nombre} con estructura inesperada: {exc}") from exc
        previas = (await db.execute(_acotar(select(func.count()).select_from(pestana.modelo), pestana))).scalar_one()
        _frenar(pestana, filas, previas)
        anomalias.extend(anom)
        parseadas.append((pestana, filas))

    fuera = sorted({f["codigo_indec"] for _, filas in parseadas for f in filas if f.get("codigo_indec")} - codigos_nomenclador)
    anomalias.extend({"tipo": "codigo_fuera_del_nomenclador", "codigo": c} for c in fuera)
    if entes:
        sin_ente = sorted({f["codigo_ente"] for _, filas in parseadas for f in filas if f.get("codigo_ente")} - set(entes))
        anomalias.extend({"tipo": "ente_fuera_del_nomenclador", "codigo": c} for c in sin_ente)

    try:
        async with db.begin_nested():
            for pestana, filas in parseadas:
                await _reemplazar(db, pestana, filas)
    except Exception as exc:  # noqa: BLE001 — el SAVEPOINT ya revirtió esta fuente
        raise _FuenteFallida(f"no se pudo guardar: {type(exc).__name__}") from exc

    insertadas = sum(len(filas) for _, filas in parseadas)
    descartadas = sum(1 for a in anomalias if a.get("tipo") in _DESCARTES)
    return leidas, insertadas, descartadas, anomalias


async def _completar_ficha_empleados(db: AsyncSession) -> None:
    """`empleados` y `masa_salarial` de la ficha restringida (Fase 1) con el último año con
    masa salarial de cada localidad."""
    filas = (
        await db.execute(
            select(ExtGobEmpleados.codigo_indec, ExtGobEmpleados.anio, ExtGobEmpleados.empleados, ExtGobEmpleados.masa_salarial)
            .where(ExtGobEmpleados.masa_salarial.is_not(None))
            .order_by(ExtGobEmpleados.anio)
        )
    ).all()
    ultimo = {c: (e, m) for c, _a, e, m in filas}  # el orden por año deja el último
    for loc in (await db.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars():
        empleados, masa = ultimo.get(loc.codigo_indec, (None, None))
        loc.empleados = empleados
        loc.masa_salarial = masa
    await db.flush()


async def _resolver_por_nombre(db: AsyncSession) -> list[dict]:
    """Código INDEC de las filas de la planilla 18 que nombran la localidad (Fase 6 §1.3), por
    nombre normalizado contra el nomenclador. Devuelve las que no resolvieron (son topónimos,
    no datos de personas)."""
    codigos = {
        parse_politico.clave_nombre(nombre): codigo
        for codigo, nombre in (
            await db.execute(select(ExtGobLocalidad.codigo_indec, ExtGobLocalidad.nombre_gob).where(ExtGobLocalidad.deleted_at.is_(None)))
        ).all()
    }
    sin_codigo: set[str] = set()
    for modelo in (ExtGobCircuitoLocalidad, ExtGobEleccionCopia):
        for fila in (await db.execute(select(modelo))).scalars():
            fila.codigo_indec = codigos.get(parse_politico.clave_nombre(fila.localidad))
            if fila.codigo_indec is None:
                sin_codigo.add(fila.localidad)
    await db.flush()
    return [{"tipo": "localidad_sin_codigo", "localidades": sorted(sin_codigo)}] if sin_codigo else []


async def _log(db: AsyncSession, fuente: str, estado: str, disparado_por: str, anomalias: list[dict], **conteos: int) -> ExtGobSyncLog:
    log = ExtGobSyncLog(
        fuente=fuente,
        estado=estado,
        anomalias=_recortar(anomalias),
        corrida_en=datetime.now(timezone.utc),
        disparado_por=disparado_por,
        filas_leidas=conteos.get("leidas", 0),
        filas_upsert=conteos.get("upsert", 0),
        filas_error=conteos.get("error", 0),
        filas_sin_match=conteos.get("sin_match", 0),
    )
    db.add(log)
    await db.flush()
    return log


async def sync_transferencias(db: AsyncSession, fuentes: list[str], disparado_por: str = "cloud-scheduler") -> list[ExtGobSyncLog]:
    """Aplica cada fuente pedida. Si fallan todas, deja los logs commiteados y lanza
    `SyncFallido` (el router devuelve 502 y `get_db` hace rollback: sin el commit explícito
    se perdería el registro de la falla)."""
    codigos = set(
        (await db.execute(select(ExtGobLocalidad.codigo_indec).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars()
    )
    entes = set((await db.execute(select(ExtGobEnte.codigo).where(ExtGobEnte.deleted_at.is_(None)))).scalars())
    logs: list[ExtGobSyncLog] = []
    for fuente in fuentes:
        try:
            leidas, insertadas, descartadas, anomalias = await _aplicar(db, fuente, codigos, entes)
        except _FuenteFallida as exc:
            logger.warning("sync transferencias de Gobierno: %s falló: %s", fuente, exc)
            logs.append(await _log(db, fuente, "fallido", disparado_por, [{"tipo": "corrida_fallida", "detalle": str(exc)}]))
            continue
        if fuente == "empleados":
            await _completar_ficha_empleados(db)
        if fuente in conciliacion.CONCEPTO_TRANSPARENCIA:
            anomalias.extend(conciliacion.resumen_para_log(await conciliacion.calcular_transparencia(db, fuente)))
        if fuente in _CONTROLES_FONDOS:
            anomalias.extend(await _CONTROLES_FONDOS[fuente](db))
        if fuente == "elecciones":
            anomalias.extend(await _resolver_por_nombre(db))
        sin_match = sum(1 for a in anomalias if a.get("tipo") == "codigo_fuera_del_nomenclador")
        logs.append(await _log(
            db, fuente, "parcial" if descartadas else "ok", disparado_por, anomalias,
            leidas=leidas, upsert=insertadas, error=descartadas, sin_match=sin_match,
        ))

    if logs and all(log.estado == "fallido" for log in logs):
        await db.commit()
        raise SyncFallido("; ".join(str((log.anomalias or [{}])[0].get("detalle")) for log in logs))
    return logs


async def get_sync_estado(db: AsyncSession) -> list[ExtGobSyncLog]:
    """Última corrida de cada fuente."""
    resultado = []
    for fuente in FUENTES:
        log = (
            await db.execute(
                select(ExtGobSyncLog).where(ExtGobSyncLog.fuente == fuente).order_by(ExtGobSyncLog.corrida_en.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if log:
            resultado.append(log)
    return resultado


async def get_conciliacion(db: AsyncSession, anio: int | None, hoy: date | None = None) -> dict:
    return {
        "transparencia": {f: await conciliacion.calcular_transparencia(db, f, anio) for f in conciliacion.CONCEPTO_TRANSPARENCIA},
        "vista": await conciliacion.calcular_vista(db, hoy or datetime.now(timezone.utc).date()),
    }
