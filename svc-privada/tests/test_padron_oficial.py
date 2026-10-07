"""Privada sobre el padrón oficial de localidades (ADR-026,
docs/files/spec-privada-padron-oficial.md): espejo, normalización en lote y
rollup por `id_geo`. svc-vivienda se simula parcheando `geo_resolver`."""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.gestiones.models import Gestion, GestionEvento
from app.integrations.geo_resolver import PadronNoDisponible
from app.territorial.models import GeoLocalidad, LocalidadInfo

_HOY = date(2026, 1, 15)

_PADRON = [
    {"id_geo": "141", "departamento": "PUNILLA", "localidad": "CHARBONIER", "lat_centro": -30.77, "lon_centro": -64.54, "activo": True},
    {"id_geo": "555", "departamento": "PUNILLA", "localidad": "CHARBONIER", "lat_centro": -30.77, "lon_centro": -64.54, "activo": False},
    {"id_geo": "546", "departamento": "MINAS", "localidad": "TOSNO", "lat_centro": None, "lon_centro": None, "activo": True},
    {"id_geo": "392", "departamento": "RÍO PRIMERO", "localidad": "MONTE CRISTO", "lat_centro": None, "lon_centro": None, "activo": True},
]

# (departamento, localidad) -> (id_geo, match_tipo), como lo resolvería svc-vivienda
_RESOLVER = {
    ("PUNILLA", "CHARBONIER"): ("141", "exacto"),
    ("PUNILLA", "Charbonier"): ("141", "exacto"),
    ("MINAS", "Tosno"): ("546", "exacto"),
    ("MINAS", "TOSNO"): ("546", "exacto"),
    ("RÍO PRIMERO", "MONTE CRISTO"): ("392", "exacto"),
    ("COLÓN", "MONTE CRISTO"): (None, "sin_match"),
    ("TULUMBA", "PARAJE EL BARRIAL"): (None, "manual"),
}


async def _resolver(items, cantidades=None):
    return [_RESOLVER.get((dep, loc), (None, "sin_match")) for dep, loc in items]


def _gestion(id_, departamento, localidad, geo_id, **kw):
    return Gestion(
        id=id_, estado=kw.pop("estado", "INGRESADO"), urgencia="Media", detalle="x",
        departamento=departamento, localidad=localidad, geo_id=geo_id, fecha_ingreso=_HOY, **kw,
    )


@pytest.fixture
def vivienda():
    """svc-vivienda simulado: padrón + resolver."""
    with patch("app.integrations.geo_resolver.fetch_padron", new=AsyncMock(return_value=_PADRON)), \
         patch("app.integrations.geo_resolver.resolver_localidades_estricto", new=AsyncMock(side_effect=_resolver)), \
         patch("app.integrations.geo_resolver.resolver_localidades", new=AsyncMock(side_effect=_resolver)) as tolerante:
        yield tolerante


# ── espejo ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_deja_el_espejo_igual_al_oficial(client, db_session, vivienda):
    db_session.add_all([
        # grafía vieja + todavía activa una fila que el oficial desactivó
        GeoLocalidad(id_geo="546", departamento="MINAS", localidad="Tosno", activo=True),
        GeoLocalidad(id_geo="555", departamento="PUNILLA", localidad="Charbonier", activo=True),
        # ya no existe en el oficial
        GeoLocalidad(id_geo="999", departamento="X", localidad="VIEJA", activo=True),
    ])
    await db_session.flush()

    r = await client.post("/internal/privada/geo/sync")
    assert r.status_code == 200
    assert r.json() == {"total_oficial": 4, "insertadas": 2, "actualizadas": 2, "desactivadas": 1}

    espejo = {g.id_geo: g for g in (await db_session.execute(select(GeoLocalidad))).scalars().all()}
    assert espejo["546"].localidad == "TOSNO"
    assert espejo["555"].activo is False
    assert espejo["141"].activo is True
    assert espejo["999"].activo is False  # se desactiva, no se borra

    # idempotente
    r = await client.post("/internal/privada/geo/sync")
    assert r.json() == {"total_oficial": 4, "insertadas": 0, "actualizadas": 0, "desactivadas": 0}


@pytest.mark.asyncio
async def test_sync_no_toca_el_espejo_si_vivienda_no_responde(client, db_session):
    db_session.add(GeoLocalidad(id_geo="546", departamento="MINAS", localidad="Tosno", activo=True))
    await db_session.flush()
    with patch("app.integrations.geo_resolver.fetch_padron", new=AsyncMock(side_effect=PadronNoDisponible("caído"))):
        r = await client.post("/internal/privada/geo/sync")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "PADRON_NO_DISPONIBLE"
    fila = (await db_session.execute(select(GeoLocalidad))).scalar_one()
    assert (fila.localidad, fila.activo) == ("Tosno", True)


@pytest.mark.asyncio
async def test_catalogo_de_localidades_no_ofrece_las_desactivadas(client, db_session):
    db_session.add_all([
        GeoLocalidad(id_geo="141", departamento="PUNILLA", localidad="CHARBONIER", activo=True),
        GeoLocalidad(id_geo="555", departamento="PUNILLA", localidad="CHARBONIER (DUPLICADA)", activo=False),
    ])
    await db_session.flush()
    r = await client.get("/api/v1/privada/catalogos/localidades", params={"departamento": "PUNILLA"})
    assert r.status_code == 200
    assert r.json() == ["CHARBONIER"]


# ── normalización en lote ───────────────────────────────────────────────────

@pytest.fixture
async def datos(db_session):
    db_session.add_all([
        GeoLocalidad(id_geo=f["id_geo"], departamento=f["departamento"], localidad=f["localidad"], activo=f["activo"])
        for f in _PADRON
    ])
    db_session.add_all([
        _gestion("g-ok", "PUNILLA", "CHARBONIER", "141"),
        _gestion("g-boot", "PUNILLA", "CHARBONIER", "BOOT|PUNILLA|CHARBONIER"),
        _gestion("g-dup", "PUNILLA", "Charbonier", "555"),
        _gestion("g-grafia", "MINAS", "Tosno", "546"),
        _gestion("g-depto", "COLÓN", "MONTE CRISTO", "392"),
        _gestion("g-paraje", "TULUMBA", "PARAJE EL BARRIAL", "BOOT|TULUMBA|PARAJE_EL_BARRIAL"),
        _gestion("g-borrada", "MINAS", "Tosno", "546", deleted_at=_HOY),
        LocalidadInfo(departamento="MINAS", localidad="Tosno"),
        LocalidadInfo(departamento="TULUMBA", localidad="PARAJE EL BARRIAL"),
    ])
    await db_session.flush()


async def _estado(db_session):
    rows = (await db_session.execute(select(Gestion))).scalars().all()
    return {g.id: (g.geo_id, g.departamento, g.localidad) for g in rows}


@pytest.mark.asyncio
async def test_normalizar_dry_run_informa_y_no_escribe(client, db_session, datos, vivienda):
    antes = await _estado(db_session)
    r = await client.post("/internal/privada/geo/normalizar-gestiones")  # dry_run por defecto
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["gestiones_activas"] == 6
    assert body["gestiones_modificadas"] == 5
    assert body["por_motivo"] == {
        "ya_correcta": 1, "repunteada_por_nombre": 2, "solo_grafia": 1, "vinculo_guardado": 1, "sin_vinculo": 1,
    }
    assert await _estado(db_session) == antes
    assert (await db_session.execute(select(GestionEvento))).scalars().all() == []


@pytest.mark.asyncio
async def test_normalizar_repunta_al_padron_oficial(client, db_session, datos, vivienda):
    r = await client.post("/internal/privada/geo/normalizar-gestiones", params={"dry_run": "false"})
    assert r.status_code == 200
    body = r.json()
    assert body["gestiones_modificadas"] == 5
    # mismo resumen que la simulación: lo ya repunteado no se cuenta dos veces
    assert body["gestiones_activas"] == 6
    assert body["por_motivo"]["ya_correcta"] == 1

    db_session.expire_all()
    estado = await _estado(db_session)
    assert estado["g-ok"] == ("141", "PUNILLA", "CHARBONIER")
    assert estado["g-boot"] == ("141", "PUNILLA", "CHARBONIER")          # id heredado del sistema viejo
    assert estado["g-dup"] == ("141", "PUNILLA", "CHARBONIER")           # apuntaba a la duplicada
    assert estado["g-grafia"] == ("546", "MINAS", "TOSNO")               # sólo cambia la grafía
    assert estado["g-depto"] == ("392", "RÍO PRIMERO", "MONTE CRISTO")   # vale el vínculo, corrige el depto
    assert estado["g-paraje"] == (None, "TULUMBA", "PARAJE EL BARRIAL")  # sin vínculo: el texto no se toca
    assert estado["g-borrada"] == ("546", "MINAS", "Tosno")              # las borradas no se tocan

    eventos = (await db_session.execute(select(GestionEvento))).scalars().all()
    assert {e.gestion_id for e in eventos} == {"g-boot", "g-dup", "g-grafia", "g-depto", "g-paraje"}
    assert {e.tipo_evento for e in eventos} == {"NORMALIZACION_LOCALIDAD"}
    ev = next(e for e in eventos if e.gestion_id == "g-depto")
    assert ev.valor_anterior == "COLÓN / MONTE CRISTO [392]"
    assert ev.valor_nuevo == "RÍO PRIMERO / MONTE CRISTO [392]"

    infos = {i.localidad: i.id_geo for i in (await db_session.execute(select(LocalidadInfo))).scalars().all()}
    assert infos == {"Tosno": "546", "PARAJE EL BARRIAL": None}  # se completa el vínculo, la clave no cambia

    # idempotente: la segunda corrida no encuentra nada que cambiar
    r = await client.post("/internal/privada/geo/normalizar-gestiones", params={"dry_run": "false"})
    assert r.json()["gestiones_modificadas"] == 0
    assert len((await db_session.execute(select(GestionEvento))).scalars().all()) == 5


@pytest.mark.asyncio
async def test_normalizar_no_escribe_si_vivienda_no_responde(client, db_session, datos):
    """Un resolver caído no puede leerse como "nada matchea" y vaciar los vínculos."""
    antes = await _estado(db_session)
    with patch(
        "app.integrations.geo_resolver.resolver_localidades_estricto",
        new=AsyncMock(side_effect=PadronNoDisponible("caído")),
    ):
        r = await client.post("/internal/privada/geo/normalizar-gestiones", params={"dry_run": "false"})
    assert r.status_code == 502
    assert await _estado(db_session) == antes


@pytest.mark.asyncio
async def test_evento_de_normalizacion_no_aparece_en_movimientos(client, db_session, datos, vivienda):
    await client.post("/internal/privada/geo/normalizar-gestiones", params={"dry_run": "false"})
    r = await client.get("/api/v1/privada/gestiones/g-grafia/eventos")
    assert r.status_code == 200
    assert r.json() == []


# ── rollup ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollup_usa_el_vinculo_guardado_y_consolida_por_id_geo(client, db_session, datos, vivienda):
    r = await client.get("/internal/privada/rollup-territorial")
    assert r.status_code == 200
    filas = {(f["departamento"], f["localidad"]): f for f in r.json()}

    # ok (141) + boot y duplicada (resueltas por nombre a 141) = una sola línea
    assert filas[("PUNILLA", "CHARBONIER")]["id_geo"] == "141"
    assert filas[("PUNILLA", "CHARBONIER")]["total_gestiones"] == 3
    # vínculo guardado válido: nombre y departamento salen del padrón, sin consultar a vivienda
    assert filas[("RÍO PRIMERO", "MONTE CRISTO")]["id_geo"] == "392"
    assert filas[("MINAS", "TOSNO")]["id_geo"] == "546"
    assert filas[("TULUMBA", "PARAJE EL BARRIAL")]["id_geo"] is None
    assert len(filas) == 4

    consultadas = set(vivienda.await_args.args[0])
    assert consultadas == {("PUNILLA", "CHARBONIER"), ("TULUMBA", "PARAJE EL BARRIAL")}
