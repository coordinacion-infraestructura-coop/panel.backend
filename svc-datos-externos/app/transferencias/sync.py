"""Orquestación del ETL de transferencias: PDF (bytes) -> filas validadas ->
resolución territorial en batch (ADR-024) -> upsert -> log de corrida.

Ver docs/files/spec-resumen-territorial-tablero-v2.md §2.3 (pasos del job) y
§2.4 (resolución territorial). No descubre ni descarga el PDF — eso vive en
`pdf_source.py` (automático) o llega como bytes del `multipart/form-data` del
endpoint de carga manual (§2.3 paso 7).
"""
import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.integrations import geo_resolver
from app.transferencias import extract, pdf_source
from app.transferencias.models import ExtTransferencia, ExtTransferenciaSyncLog
from app.transferencias.schemas import SyncResultResponse

logger = logging.getLogger(__name__)

_MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


class ExtraccionFallida(Exception):
    """El PDF no pudo parsearse (layout inesperado). Se loguea la corrida
    igual que cualquier otra, pero se re-lanza para que el endpoint devuelva
    un error HTTP real — no hay nada que upsertear."""


async def _log_falla(db: AsyncSession, periodo: date, tipo: str, disparado_por: str, motivo: str) -> None:
    log = ExtTransferenciaSyncLog(
        periodo=periodo,
        tipo=tipo,
        filas_procesadas=0,
        filas_sin_match=0,
        anomalias=[{"tipo": "extraccion_fallida", "detalle": motivo}],
        disparado_por=disparado_por,
    )
    db.add(log)
    await db.flush()


async def sync_desde_pdf(
    db: AsyncSession,
    pdf_bytes: bytes,
    tipo: str,
    periodo: date,
    disparado_por: str = "manual",
) -> SyncResultResponse:
    periodo_label = periodo.strftime("%Y-%m")

    # pdfplumber necesita un path real (se reabre el archivo dos veces:
    # compute_column_bins + el parseo completo) — un BytesIO ya consumido en
    # la primera pasada rompería la segunda.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        try:
            filas, totales_depto, total_general, duplicados = extract.extract_pdf(
                tmp_path, tipo, periodo_label
            )
        except extract.ExtraccionError as exc:
            await _log_falla(db, periodo, tipo, disparado_por, str(exc))
            raise ExtraccionFallida(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    anomalias: list[dict[str, Any]] = []

    discrepancias = extract.validar_totales(filas, totales_depto, total_general)
    for d in discrepancias:
        anomalias.append({"tipo": "discrepancia_total", "detalle": d})

    for depto_key, nombre_tal_cual in duplicados:
        anomalias.append({
            "tipo": "total_duplicado",
            "detalle": f"{depto_key} aparece de nuevo como fila TOTAL ({nombre_tal_cual!r}) — "
                       f"posible error de copiado en el PDF original, revisar manualmente.",
        })

    # Resolución territorial en batch — una sola llamada a svc-vivienda para
    # toda la corrida (ADR-024), no una por fila.
    pares_unicos = sorted({(f["departamento_pdf"], f["nombre_pdf"]) for f in filas})
    resueltos = await geo_resolver.resolver_localidades(pares_unicos)
    resolucion: dict[tuple[str, str], tuple[str | None, str | None]] = {
        par: res for par, res in zip(pares_unicos, resueltos)
    }

    ids_geo = {id_geo for id_geo, _ in resolucion.values() if id_geo}
    codigos_indec: dict[str, str] = {}
    if ids_geo:
        rows = (
            await db.execute(select(ExtGeoCenso.id_geo, ExtGeoCenso.codigo_indec).where(ExtGeoCenso.id_geo.in_(ids_geo)))
        ).all()
        codigos_indec = {r.id_geo: r.codigo_indec for r in rows}

    filas_procesadas = 0
    filas_sin_match = 0
    for f in filas:
        par = (f["departamento_pdf"], f["nombre_pdf"])
        id_geo, match_tipo = resolucion.get(par, (None, None))
        if id_geo is None:
            filas_sin_match += 1
            anomalias.append({
                "tipo": "sin_match",
                "detalle": f"{f['departamento_pdf']} / {f['nombre_pdf']} no matcheó contra el padrón.",
            })
        try:
            # SAVEPOINT por fila — una fila mala no debe tirar todo el batch
            # (mismo patrón que app/cordon_cuneta/checklist_sync.py).
            async with db.begin_nested():
                existing = (
                    await db.execute(
                        select(ExtTransferencia).where(
                            ExtTransferencia.periodo == periodo,
                            ExtTransferencia.tipo == tipo,
                            ExtTransferencia.nombre_pdf == f["nombre_pdf"],
                            ExtTransferencia.concepto == f["concepto"],
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.monto = f["monto"]
                    existing.departamento_pdf = f["departamento_pdf"]
                    existing.id_geo = id_geo
                    existing.codigo_indec = codigos_indec.get(id_geo) if id_geo else None
                    existing.match_tipo = match_tipo
                else:
                    db.add(ExtTransferencia(
                        periodo=periodo,
                        tipo=tipo,
                        departamento_pdf=f["departamento_pdf"],
                        nombre_pdf=f["nombre_pdf"],
                        concepto=f["concepto"],
                        monto=f["monto"],
                        id_geo=id_geo,
                        codigo_indec=codigos_indec.get(id_geo) if id_geo else None,
                        match_tipo=match_tipo,
                    ))
            filas_procesadas += 1
        except Exception as exc:  # noqa: BLE001 — una fila con error no frena el resto
            anomalias.append({
                "tipo": "error_fila",
                "detalle": f"{f['nombre_pdf']} / {f['concepto']}: {exc}",
            })

    log = ExtTransferenciaSyncLog(
        periodo=periodo,
        tipo=tipo,
        filas_procesadas=filas_procesadas,
        filas_sin_match=filas_sin_match,
        anomalias=anomalias,
        corrida_en=datetime.now(timezone.utc),
        disparado_por=disparado_por,
    )
    db.add(log)
    await db.flush()

    return SyncResultResponse(
        periodo=periodo,
        tipo=tipo,
        filas_procesadas=filas_procesadas,
        filas_sin_match=filas_sin_match,
        anomalias=[a["detalle"] for a in anomalias],
    )


async def sync_periodo_automatico(
    db: AsyncSession,
    tipo: str,
    periodo: date,
    disparado_por: str = "cloud-scheduler",
) -> SyncResultResponse:
    """Descubre el link del PDF del período en transparencia.cba.gov.ar, lo
    descarga y corre `sync_desde_pdf`. Job mensual (día 5, da margen a que el
    PDF del mes anterior ya esté publicado) — ver spec §2.3 pasos 1-2. Si el
    sitio bloquea el scraping o cambia de formato, la falla queda logueada y
    el operador usa el endpoint de carga manual (§2.3 paso 7) como respaldo."""
    periodo_label = f"{_MESES_ES[periodo.month - 1]}-{periodo.year}"
    try:
        links = await pdf_source.descubrir_links(tipo, periodo_label)
        pdf_bytes = await pdf_source.descargar_pdf(links[0])
    except pdf_source.DescubrimientoError as exc:
        await _log_falla(db, periodo, tipo, disparado_por, str(exc))
        raise ExtraccionFallida(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — red/HTTP inesperado, tratar igual que descubrimiento fallido
        await _log_falla(db, periodo, tipo, disparado_por, f"Fallo al descargar el PDF: {exc}")
        raise ExtraccionFallida(str(exc)) from exc

    return await sync_desde_pdf(db, pdf_bytes, tipo, periodo, disparado_por=disparado_por)


async def get_last_sync_status(db: AsyncSession, tipo: str | None = None) -> ExtTransferenciaSyncLog | None:
    stmt = select(ExtTransferenciaSyncLog).order_by(ExtTransferenciaSyncLog.corrida_en.desc())
    if tipo:
        stmt = stmt.where(ExtTransferenciaSyncLog.tipo == tipo)
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()
