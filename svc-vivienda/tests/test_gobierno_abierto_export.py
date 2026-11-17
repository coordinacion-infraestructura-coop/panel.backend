"""Exportación de pagos de Vivienda a la planilla de Gobierno Abierto.

spec-export-gobierno-abierto-vivienda.md · ADR-034.
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico.models import ChecklistObraHito, ChecklistTecnico
from app.config import settings
from app.geo.models import GeoLocalidad
from app.gobierno_abierto import export_vivienda
from app.gobierno_abierto.export_vivienda import EntidadExport, armar_fila
from app.gobierno_abierto.models import GobAbiertoSyncLog
from app.mi_lugar.models import ProyectoML
from tests.conftest import TestSession
from tests.test_checklist_tecnico import (  # noqa: F401 — fixtures compartidos
    BASE,
    catalogos,
    localidad_ch,
    municipio_cc,
    proyecto_ml,
)

D1, D2, D3, D4 = date(2026, 3, 1), date(2026, 5, 10), date(2026, 8, 20), date(2026, 11, 2)


async def _hitos(db: AsyncSession, programa: str, entidad_id: str, **fechas: date) -> None:
    """fechas: anticipo=, h40=, h70=, h100=."""
    cid = str(uuid.uuid4())
    db.add(ChecklistTecnico(id=cid, programa=programa, entidad_id=entidad_id))
    for tipo, clave in (("anticipo", "anticipo"), ("40", "h40"), ("70", "h70"), ("100", "h100")):
        db.add(ChecklistObraHito(id=str(uuid.uuid4()), checklist_id=cid, tipo=tipo, fecha_acreditado=fechas.get(clave)))
    await db.flush()


# ── armar_fila (puro) ────────────────────────────────────────────────────────

ENT = EntidadExport(programa="cc", entidad_id="abc", localidad="Chazón", departamento="General San Martín", monto=100_000_000)


def test_sin_anticipo_no_hay_fila():
    assert armar_fila(ENT, {"anticipo": None, "40": D2}) is None


def test_solo_anticipo():
    f = armar_fila(ENT, {"anticipo": D1})
    assert f[:7] == [
        "Chazón", "General San Martín", "Cordón Cuneta", "2026-03-01", 50_000_000.0,
        "Avance físico 40%, Avance físico 70%, Avance físico 100%", 50_000_000.0,
    ]
    assert f[7:13] == ["", "", "", "", "", ""]
    assert f[13] == 100_000_000
    assert f[14] == "CC-abc"
    assert f[15] == ""  # sin cantidades cargadas
    assert len(f) == 16  # B:Q


def test_todos_pagos_100_es_saldo_cero():
    f = armar_fila(ENT, {"anticipo": D1, "40": D2, "70": D3, "100": D4})
    assert f[5] == "Ninguna"
    assert f[6] == 0.0
    assert f[7:13] == ["2026-05-10", 25_000_000.0, "2026-08-20", 25_000_000.0, "2026-11-02", 0.0]


def test_sin_monto_convenio_deja_montos_vacios():
    ent = EntidadExport(programa="ch", entidad_id="x", localidad="L", departamento="D", monto=None)
    f = armar_fila(ent, {"anticipo": D1, "40": D2})
    assert f[2] == "Córdoba Hogar"
    assert f[4] == "" and f[6] == "" and f[8] == "" and f[13] == ""
    assert f[5] == "Avance físico 70%, Avance físico 100%"


def test_ml_lleva_nombre_de_proyecto_en_id():
    ent = EntidadExport(programa="ml", entidad_id="p1", localidad="L", departamento="D", monto=10.0, nombre_proyecto="Predio Norte")
    assert armar_fila(ent, {"anticipo": D1})[14] == "ML-p1 · Predio Norte"


# ── construir_filas (base) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_construir_filas_tres_programas_y_orden(
    db_session: AsyncSession, municipio_cc: str, localidad_ch: str, proyecto_ml: str
):
    await _hitos(db_session, "cc", municipio_cc, anticipo=D2, h40=D3)
    await _hitos(db_session, "ch", localidad_ch, anticipo=D1)
    await _hitos(db_session, "ml", proyecto_ml)  # sin anticipo -> no va
    filas = await export_vivienda.construir_filas(db_session)
    assert [f[2] for f in filas] == ["Córdoba Hogar", "Cordón Cuneta"]  # orden por fecha de anticipo
    assert filas[1][7] == "2026-08-20"
    assert filas[1][8] == 25_000_000.0
    assert filas[0][15] == "80 viviendas"  # fixture localidad_ch


@pytest.mark.asyncio
async def test_construir_filas_usa_padron_oficial_y_excluye_bajas(
    db_session: AsyncSession, municipio_cc: str, localidad_ch: str
):
    from app.cordoba_hogar.models import LocalidadCordobaHogar
    from app.cordon_cuneta.models import MunicipioCordonCuneta

    db_session.add(GeoLocalidad(id_geo="14042010", departamento="GENERAL SAN MARTIN", localidad="CHAZON"))
    cc = await db_session.get(MunicipioCordonCuneta, municipio_cc)
    cc.localidad_id = "14042010"
    ch = await db_session.get(LocalidadCordobaHogar, localidad_ch)
    ch.deleted_at = datetime.now(timezone.utc)
    await _hitos(db_session, "cc", municipio_cc, anticipo=D1)
    await _hitos(db_session, "ch", localidad_ch, anticipo=D1)
    filas = await export_vivienda.construir_filas(db_session)
    assert len(filas) == 1
    assert filas[0][:2] == ["CHAZON", "GENERAL SAN MARTIN"]


@pytest.mark.asyncio
async def test_ml_dos_proyectos_misma_localidad_son_dos_filas(db_session: AsyncSession, proyecto_ml: str):
    otro = str(uuid.uuid4())
    db_session.add(ProyectoML(id=otro, tipo="muni", nombre="Predio Sur", localidad_nombre="Villa María",
                              departamento="General San Martín", monto=20_000_000))
    await db_session.flush()
    await _hitos(db_session, "ml", proyecto_ml, anticipo=D1)
    await _hitos(db_session, "ml", otro, anticipo=D1)
    filas = await export_vivienda.construir_filas(db_session)
    assert len(filas) == 2
    assert {f[0] for f in filas} == {"Villa María"}
    assert {f[14].split(" · ")[1] for f in filas} == {"Predio Norte", "Predio Sur"}


# ── sincronizar ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sincronizar_escribe_b_a_q_y_borra_sobrante(db_session: AsyncSession, municipio_cc: str):
    await _hitos(db_session, "cc", municipio_cc, anticipo=D1)
    escribir = AsyncMock()
    with patch.object(settings, "gobabierto_sheet_id", "SHEET"), \
         patch("app.gobierno_abierto.export_vivienda.google_sheets.update_and_clear", escribir):
        n = await export_vivienda.sincronizar(db_session, origen="manual")
    assert n == 1
    sheet_id, updates, clear_range = escribir.await_args.args
    assert sheet_id == "SHEET"
    rangos = [r for r, _ in updates]
    assert rangos == ["'Vivienda'!B1:Q1", "'Vivienda'!B2:Q2"]
    assert clear_range == "'Vivienda'!B3:Q"
    assert all("!A" not in r for r in rangos + [clear_range])  # la columna A nunca se toca
    log = (await db_session.execute(select(GobAbiertoSyncLog))).scalar_one()
    assert log.ok and log.filas == 1 and log.origen == "manual"


@pytest.mark.asyncio
async def test_sincronizar_sin_filas_borra_todo_debajo_de_encabezados(db_session: AsyncSession):
    escribir = AsyncMock()
    with patch.object(settings, "gobabierto_sheet_id", "SHEET"), \
         patch("app.gobierno_abierto.export_vivienda.google_sheets.update_and_clear", escribir):
        assert await export_vivienda.sincronizar(db_session, origen="manual") == 0
    _, updates, clear_range = escribir.await_args.args
    assert [r for r, _ in updates] == ["'Vivienda'!B1:Q1"]
    assert clear_range == "'Vivienda'!B2:Q"


@pytest.mark.asyncio
async def test_falla_de_google_queda_en_log_y_notifica_si_es_scheduler(db_session: AsyncSession):
    notificar = AsyncMock()
    with patch.object(settings, "gobabierto_sheet_id", "SHEET"), \
         patch("app.gobierno_abierto.export_vivienda.google_sheets.update_and_clear",
               AsyncMock(side_effect=RuntimeError("403 caller does not have permission"))), \
         patch("app.gobierno_abierto.export_vivienda.notificaciones_service.crear", notificar):
        with pytest.raises(export_vivienda.GobAbiertoSyncError):
            await export_vivienda.sincronizar(db_session, origen="scheduler")
    log = (await db_session.execute(select(GobAbiertoSyncLog))).scalar_one()
    assert not log.ok and "403" in log.error
    notificar.assert_awaited_once()
    assert notificar.await_args.args[2]["destino_valor"] == "Admin"


# ── Disparo desde el PATCH de hito ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_hito_responde_200_aunque_falle_sheets(
    client: AsyncClient, municipio_cc: str, catalogos: None
):
    with patch.object(settings, "gobabierto_export_enabled", True), \
         patch.object(settings, "gobabierto_sheet_id", "SHEET"), \
         patch.object(export_vivienda, "_session_factory", TestSession), \
         patch("app.gobierno_abierto.export_vivienda.google_sheets.update_and_clear",
               AsyncMock(side_effect=RuntimeError("Google caído"))) as escribir:
        r = await client.patch(f"{BASE}/cc/{municipio_cc}/hitos/anticipo", json={"fecha_acreditado": "2026-03-01"})
    assert r.status_code == 200
    escribir.assert_awaited()  # la corrida en segundo plano se intentó


@pytest.mark.asyncio
async def test_patch_hito_con_flag_apagado_no_escribe(client: AsyncClient, municipio_cc: str, catalogos: None):
    with patch("app.gobierno_abierto.export_vivienda.google_sheets.update_and_clear", AsyncMock()) as escribir:
        r = await client.patch(f"{BASE}/cc/{municipio_cc}/hitos/anticipo", json={"fecha_acreditado": "2026-03-01"})
    assert r.status_code == 200
    escribir.assert_not_awaited()


# ── Columna Detalle ──────────────────────────────────────────────────────────

class _E:
    def __init__(self, **kw):
        self.__dict__.update(dict(cordon_cuneta_ml=None, adoquinado_m2=None, cantidad_casas=None,
                                  lotes=None, superficie=None) | kw)


def test_detalle_por_programa():
    from decimal import Decimal
    from app.gobierno_abierto.export_vivienda import detalle_entidad
    assert detalle_entidad("cc", _E(cordon_cuneta_ml=1200, adoquinado_m2=Decimal("3500.50"))) ==         "1.200 m de cordón cuneta · 3.500,5 m² de adoquinado"
    assert detalle_entidad("cc", _E(adoquinado_m2=800)) == "800 m² de adoquinado"
    assert detalle_entidad("ch", _E(cantidad_casas=1)) == "1 vivienda"
    assert detalle_entidad("ch", _E(cantidad_casas=80)) == "80 viviendas"
    assert detalle_entidad("ml", _E(lotes=20, superficie=Decimal("1.5000"))) == "20 lotes · 1,5 ha"
    assert detalle_entidad("ml", _E()) == ""
