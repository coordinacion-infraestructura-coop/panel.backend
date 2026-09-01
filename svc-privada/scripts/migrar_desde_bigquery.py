#!/usr/bin/env python3
"""ETL one-shot: BigQuery `infra_gestion` -> PostgreSQL `db_privada` (Fase 4).

Spec: docs/files/spec-migracion-svc-privada.md §5, §8.

Uso (desde services/svc-privada/, con el proxy de Cloud SQL activo y DATABASE_URL
apuntando a db_privada):

    pip install -e ".[etl]"
    export DATABASE_URL="postgresql+asyncpg://user_privada:PASS@127.0.0.1:5432/db_privada"
    export BQ_PROJECT=essential-haiku-482815-u4        # (default)
    python scripts/migrar_desde_bigquery.py --dry-run   # lee BQ, transforma, reporta; no escribe
    python scripts/migrar_desde_bigquery.py --truncate  # carga real (borra priv_* primero)

Transformaciones (§5):
  - gestiones.id_gestion -> id_legacy ; se genera un UUID nuevo como id (mapa id_legacy->id)
  - is_deleted=TRUE -> deleted_at (fecha del último evento ARCHIVO, o now())
  - '' en columnas nullable -> NULL
  - TIMESTAMP -> TIMESTAMPTZ (UTC) ; DATE -> date
  - estado=FINALIZADA sin fecha_finalizacion -> se completa (RE-9): último CAMBIO_ESTADO a
    FINALIZADA, si no hay, fecha de fecha_estado
  - gestiones_eventos.id_gestion -> gestion_id (resuelto por el mapa)
  - metadata_json: si viene como STRING JSON se parsea a dict
  - geo_localidades.lat_centro/lon_centro -> lat/lon
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, text  # noqa: E402

from app.catalogos.models import (  # noqa: E402
    CatCanalOrigen, CatCategoriaGeneral, CatEstado, CatMinisterioAgencia,
    CatTipoGestion, CatUrgencia,
)
from app.database import AsyncSessionLocal, engine  # noqa: E402
from app.gestiones.models import Gestion, GestionEvento  # noqa: E402
from app.territorial.models import DepartamentoInfo, GeoLocalidad, LocalidadInfo  # noqa: E402

BQ_PROJECT = os.getenv("BQ_PROJECT", "essential-haiku-482815-u4")
BQ_DATASET = os.getenv("BQ_DATASET", "infra_gestion")
BQ_LOCATION = os.getenv("BQ_LOCATION", "southamerica-east1")

_CAT = {
    "cat_estado": CatEstado, "cat_urgencia": CatUrgencia,
    "cat_ministerio_agencia": CatMinisterioAgencia, "cat_categoria_general": CatCategoriaGeneral,
    "cat_tipo_gestion": CatTipoGestion, "cat_canal_origen": CatCanalOrigen,
}
_CAT_ORDER = list(_CAT)
_PRIV_TABLES = [
    "priv_gestiones_eventos", "priv_gestiones", "priv_departamentos_info",
    "priv_localidades_info", "priv_geo_localidades",
    "priv_cat_canal_origen", "priv_cat_tipo_gestion", "priv_cat_categoria_general",
    "priv_cat_ministerio_agencia", "priv_cat_urgencia", "priv_cat_estado",
]


# ── BigQuery ────────────────────────────────────────────────────────────────

def bq_rows(table_or_sql: str, is_sql: bool = False) -> list[dict]:
    from google.cloud import bigquery

    client = bigquery.Client(project=BQ_PROJECT)
    sql = table_or_sql if is_sql else f"SELECT * FROM `{BQ_PROJECT}.{BQ_DATASET}.{table_or_sql}`"
    job = client.query(sql, location=BQ_LOCATION)
    return [dict(r) for r in job.result()]


# ── helpers de transformación ──────────────────────────────────────────────

def s(v):
    """'' / whitespace -> None ; deja el resto igual."""
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def ts(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(v)).replace(tzinfo=timezone.utc)


def d(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v)[:10])


def num(v):
    if v is None:
        return None
    return Decimal(str(v))


def meta_to_dict(v):
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return {"_raw": v}
    return v


# ── carga ──────────────────────────────────────────────────────────────────

async def _truncate(session):
    await session.execute(text("TRUNCATE " + ", ".join(_PRIV_TABLES) + " RESTART IDENTITY CASCADE"))
    await session.flush()


async def run(dry_run: bool, truncate: bool, limit: int | None):
    report: dict[str, int] = {}

    # BQ reads
    print(">>> leyendo BigQuery...")
    cats = {t: bq_rows(t) for t in _CAT_ORDER}
    geo = bq_rows("geo_localidades")
    loc_info = bq_rows("localidades_info")
    dep_info = bq_rows("departamentos_info")
    gestiones = bq_rows("gestiones")
    eventos = bq_rows("gestiones_eventos")
    if limit:
        gestiones = gestiones[:limit]

    # eventos: último ARCHIVO y último CAMBIO_ESTADO->FINALIZADA por id_gestion
    ultimo_archivo: dict[str, datetime] = {}
    ultimo_finalizada: dict[str, datetime] = {}
    for e in eventos:
        gid = e["id_gestion"]
        fe = ts(e.get("fecha_evento"))
        if e.get("tipo_evento") == "ARCHIVO" and fe:
            ultimo_archivo[gid] = max(ultimo_archivo.get(gid, fe), fe)
        if e.get("tipo_evento") == "CAMBIO_ESTADO" and e.get("estado_nuevo") == "FINALIZADA" and fe:
            ultimo_finalizada[gid] = max(ultimo_finalizada.get(gid, fe), fe)

    # transform gestiones + mapa id_legacy -> id nuevo
    id_map: dict[str, str] = {}
    g_rows = []
    finalizadas_backfill = 0
    for g in gestiones:
        legacy = g["id_gestion"]
        new_id = str(uuid.uuid4())
        id_map[legacy] = new_id
        borrada = bool(g.get("is_deleted"))
        deleted_at = None
        if borrada:
            deleted_at = ultimo_archivo.get(legacy) or ts(g.get("updated_at")) or datetime.now(timezone.utc)

        estado = s(g.get("estado"))
        fecha_fin = d(g.get("fecha_finalizacion"))
        if estado == "FINALIZADA" and fecha_fin is None:
            ff = ultimo_finalizada.get(legacy) or ts(g.get("fecha_estado"))
            fecha_fin = ff.date() if ff else None
            if fecha_fin:
                finalizadas_backfill += 1

        g_rows.append(dict(
            id=new_id, id_legacy=legacy,
            nro_expediente=s(g.get("nro_expediente")), origen=s(g.get("origen")),
            estado=estado or "INGRESADO", fecha_ingreso=d(g.get("fecha_ingreso")),
            fecha_estado=ts(g.get("fecha_estado")), fecha_finalizacion=fecha_fin,
            urgencia=s(g.get("urgencia")) or "Media",
            ministerio_agencia_id=s(g.get("ministerio_agencia_id")),
            organismo_id=s(g.get("organismo_id")), derivado_a_id=s(g.get("derivado_a_id")),
            categoria_general_id=s(g.get("categoria_general_id")),
            subcategoria_id=s(g.get("subcategoria_id")),
            tipo_demanda_principal_id=s(g.get("tipo_demanda_principal_id")),
            subtipo_detalle=s(g.get("subtipo_detalle")),
            detalle=g.get("detalle") or "", observaciones=s(g.get("observaciones")),
            geo_id=s(g.get("geo_id")), departamento=g.get("departamento") or "",
            localidad=g.get("localidad") or "", direccion=s(g.get("direccion")),
            lat=num(g.get("lat")), lon=num(g.get("lon")),
            costo_estimado=num(g.get("costo_estimado")), costo_moneda=s(g.get("costo_moneda")),
            tipo_gestion=s(g.get("tipo_gestion")), canal_origen=s(g.get("canal_origen")),
            created_at=ts(g.get("created_at")) or datetime.now(timezone.utc),
            updated_at=ts(g.get("updated_at")) or datetime.now(timezone.utc),
            created_by=s(g.get("created_by")), updated_by=s(g.get("updated_by")),
            deleted_at=deleted_at,
        ))

    e_rows = []
    huerfanos = 0
    for e in eventos:
        gid = id_map.get(e["id_gestion"])
        if gid is None:
            huerfanos += 1
            continue
        e_rows.append(dict(
            id=e["id_evento"], gestion_id=gid, fecha_evento=ts(e.get("fecha_evento")),
            usuario=e.get("usuario") or "", rol_usuario=s(e.get("rol_usuario")),
            tipo_evento=e.get("tipo_evento") or "?",
            estado_anterior=s(e.get("estado_anterior")), estado_nuevo=s(e.get("estado_nuevo")),
            campo_modificado=s(e.get("campo_modificado")),
            valor_anterior=s(e.get("valor_anterior")), valor_nuevo=s(e.get("valor_nuevo")),
            comentario=s(e.get("comentario")), metadata_json=meta_to_dict(e.get("metadata_json")),
        ))

    report = {
        "cat_total": sum(len(v) for v in cats.values()),
        "geo": len(geo), "localidades_info": len(loc_info), "departamentos_info": len(dep_info),
        "gestiones": len(g_rows), "gestiones_borradas": sum(1 for r in g_rows if r["deleted_at"]),
        "eventos": len(e_rows), "eventos_huerfanos": huerfanos,
        "fecha_finalizacion_backfill": finalizadas_backfill,
    }
    print(">>> transformado:", json.dumps(report, indent=2, ensure_ascii=False))

    if dry_run:
        print(">>> DRY-RUN: no se escribe nada.")
        return

    async with AsyncSessionLocal() as session:
        if truncate:
            print(">>> TRUNCATE priv_*")
            await _truncate(session)

        for t in _CAT_ORDER:
            model = _CAT[t]
            session.add_all([model(id=r["id"], nombre=r.get("nombre"), orden=r.get("orden"),
                                   activo=bool(r.get("activo", True)), descripcion=s(r.get("descripcion")))
                             for r in cats[t]])
        session.add_all([GeoLocalidad(id_geo=r["id_geo"], departamento=r.get("departamento") or "",
                                      localidad=r.get("localidad") or "",
                                      lat=num(r.get("lat_centro")), lon=num(r.get("lon_centro")),
                                      activo=bool(r.get("activo", True))) for r in geo])
        session.add_all([LocalidadInfo(
            departamento=r["departamento"], localidad=r["localidad"], habitantes=r.get("habitantes"),
            electores=r.get("electores"), intendente_jefe_comunal=s(r.get("intendente_jefe_comunal")),
            partido_politico=s(r.get("partido_politico")), tipo_localidad=s(r.get("tipo_localidad")),
            color_semaforo=s(r.get("color_semaforo")), created_at=ts(r.get("created_at")),
            created_by=s(r.get("created_by")), updated_at=ts(r.get("updated_at")),
            updated_by=s(r.get("updated_by"))) for r in loc_info])
        session.add_all([DepartamentoInfo(
            departamento=r["departamento"], habitantes=r.get("habitantes"), electores=r.get("electores"),
            legislador_departamental=s(r.get("legislador_departamental")),
            partido_politico=s(r.get("partido_politico")),
            legislador_sabana1=s(r.get("legislador_sabana1")),
            partido_politico_sabana1=s(r.get("partido_politico_sabana1")),
            legislador_sabana2=s(r.get("legislador_sabana2")),
            partido_politico_sabana2=s(r.get("partido_politico_sabana2")),
            created_at=ts(r.get("created_at")), created_by=s(r.get("created_by")),
            updated_at=ts(r.get("updated_at")), updated_by=s(r.get("updated_by"))) for r in dep_info])
        await session.flush()

        session.add_all([Gestion(**r) for r in g_rows])
        await session.flush()
        session.add_all([GestionEvento(**r) for r in e_rows])
        await session.commit()
        print(">>> commit OK")

    await _verificar()


async def _verificar():
    """Compara agregados PG vs baseline BQ (Anexo ETL_baseline)."""
    print(">>> verificación (PG):")
    async with AsyncSessionLocal() as session:
        total = (await session.execute(select(func.count()).select_from(Gestion))).scalar_one()
        activas = (await session.execute(
            select(func.count()).select_from(Gestion).where(Gestion.deleted_at.is_(None)))).scalar_one()
        fin = (await session.execute(
            select(func.count()).select_from(Gestion).where(Gestion.estado == "FINALIZADA"))).scalar_one()
        fin_sin_fecha = (await session.execute(
            select(func.count()).select_from(Gestion).where(
                Gestion.estado == "FINALIZADA", Gestion.fecha_finalizacion.is_(None)))).scalar_one()
        eventos = (await session.execute(select(func.count()).select_from(GestionEvento))).scalar_one()
        loc = (await session.execute(select(func.count()).select_from(LocalidadInfo))).scalar_one()
        dep = (await session.execute(select(func.count()).select_from(DepartamentoInfo))).scalar_one()
        geo = (await session.execute(select(func.count()).select_from(GeoLocalidad))).scalar_one()
    print(json.dumps({
        "gestiones_total": total, "gestiones_activas": activas, "gestiones_finalizadas": fin,
        "finalizadas_sin_fecha": fin_sin_fecha, "eventos_total": eventos,
        "localidades_info": loc, "departamentos_info": dep, "geo_localidades": geo,
    }, indent=2))
    print("    -> comparar contra anexos/ETL_baseline.json (Anexo D / línea base).")
    print("    -> `finalizadas_sin_fecha` debería ser 0 (RE-9).")
    await engine.dispose()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="lee BQ, transforma y reporta; no escribe")
    ap.add_argument("--truncate", action="store_true", help="TRUNCATE priv_* antes de cargar")
    ap.add_argument("--limit", type=int, default=None, help="sólo N gestiones (pruebas)")
    args = ap.parse_args()
    asyncio.run(run(args.dry_run, args.truncate, args.limit))


if __name__ == "__main__":
    main()
