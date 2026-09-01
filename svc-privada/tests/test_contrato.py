"""Tests de contrato: la forma (keys) de las respuestas nuevas coincide con las
del sistema viejo capturadas en anexos/D/ (Anexo D).

Se saltean si anexos/D/ no está (CI / clone limpio). Comparan estructura, no valores:
- key sets de objetos y del primer item de listas
- se ignoran diferencias de encoding (el viejo devuelve mojibake en textos)
"""
import json
from pathlib import Path

import pytest
import pytest_asyncio

from app.catalogos.models import CatCategoriaGeneral, CatEstado, CatMinisterioAgencia, CatUrgencia
from app.gestiones.models import Gestion, GestionEvento
from app.territorial.models import DepartamentoInfo, GeoLocalidad, LocalidadInfo
from datetime import date, datetime, timezone

FIXT = Path(__file__).resolve().parent.parent / "anexos" / "D"
pytestmark = pytest.mark.skipif(not FIXT.exists(), reason="anexos/D/ ausente (se genera con scripts/obtener_anexo_D.sh)")

NOW = datetime(2026, 8, 31, 13, 0, tzinfo=timezone.utc)


def _load(name):
    return json.loads((FIXT / name).read_text(encoding="utf-8"))


def _keys(obj):
    return set(obj.keys()) if isinstance(obj, dict) else set()


@pytest_asyncio.fixture
async def seed(db_session):
    db = db_session
    db.add_all([
        GeoLocalidad(id_geo="508", departamento="CALAMUCHITA", localidad="AMBOY", lat=-32.17, lon=-64.57, activo=True),
        CatEstado(id="INGRESADO", nombre="INGRESADO", orden=10, activo=True),
        CatUrgencia(id="Alta", nombre="Alta", orden=10, activo=True),
        CatMinisterioAgencia(id="MIN_GOBIERNO", nombre="Gobierno", orden=10, activo=True),
        CatCategoriaGeneral(id="CAT_OBRA_DE_GAS", nombre="Gas", orden=10, activo=True),
        LocalidadInfo(departamento="CALAMUCHITA", localidad="AMBOY", habitantes=1, electores=1),
        DepartamentoInfo(departamento="CALAMUCHITA", habitantes=1, electores=1),
    ])
    g = Gestion(
        id="11111111-1111-1111-1111-111111111111", origen="APP", estado="INGRESADO",
        fecha_ingreso=date(2026, 8, 31), fecha_estado=NOW, urgencia="Media",
        ministerio_agencia_id="MIN_GOBIERNO", categoria_general_id="CAT_OBRA_DE_GAS",
        detalle="OBRA DE GAS", departamento="CALAMUCHITA", localidad="AMBOY", geo_id="508",
        lat=-32.17, lon=-64.57, created_at=NOW, updated_at=NOW,
    )
    db.add(g)
    db.add(GestionEvento(id="ev-1", gestion_id=g.id, fecha_evento=NOW, usuario="x@x.com",
                         tipo_evento="CREACION", estado_nuevo="INGRESADO", metadata_json={"a": 1}))
    await db.flush()
    return g.id


@pytest.mark.asyncio
async def test_gestiones_list_keys(client, seed):
    viejo = _load("gestiones_list.json")
    nuevo = (await client.get("/api/v1/privada/gestiones", params={"limit": 5})).json()
    assert _keys(nuevo) == _keys(viejo)
    assert _keys(nuevo["items"][0]) == _keys(viejo["items"][0])


@pytest.mark.asyncio
async def test_gestion_detalle_keys(client, seed):
    viejo = _load("gestion_detalle.json")
    nuevo = (await client.get(f"/api/v1/privada/gestiones/{seed}")).json()
    assert _keys(nuevo) == _keys(viejo)


@pytest.mark.asyncio
async def test_gestion_eventos_keys(client, seed):
    viejo = _load("gestion_eventos.json")
    nuevo = (await client.get(f"/api/v1/privada/gestiones/{seed}/eventos")).json()
    if viejo:
        assert _keys(nuevo[0]) == _keys(viejo[0])


@pytest.mark.asyncio
async def test_resumen_territorial_keys(client, seed):
    viejo = _load("resumen_localidad.json")
    nuevo = (await client.get("/api/v1/privada/gestiones/resumen-territorial",
                              params={"departamento": "CALAMUCHITA", "localidad": "AMBOY"})).json()
    assert _keys(nuevo) == _keys(viejo)
    assert _keys(nuevo["metricas"]) == _keys(viejo["metricas"])
    assert _keys(nuevo["territorio_info"]) == _keys(viejo["territorio_info"])
    if viejo["gestiones"] and nuevo["gestiones"]:
        assert _keys(nuevo["gestiones"][0]["gestion"]) == _keys(viejo["gestiones"][0]["gestion"])


@pytest.mark.asyncio
@pytest.mark.parametrize("cat,fx", [
    ("estados", "catalogo_estados.json"),
    ("urgencias", "catalogo_urgencias.json"),
    ("ministerios", "catalogo_ministerios.json"),
    ("categorias", "catalogo_categorias.json"),
])
async def test_catalogos_keys(client, seed, cat, fx):
    viejo = _load(fx)
    nuevo = (await client.get(f"/api/v1/privada/catalogos/{cat}")).json()
    if viejo and nuevo:
        assert _keys(nuevo[0]) == _keys(viejo[0])


@pytest.mark.asyncio
async def test_me_keys(client):
    assert _keys((await client.get("/api/v1/privada/me")).json()) == _keys(_load("me.json"))


@pytest.mark.asyncio
async def test_informe_resumen_keys(client, seed):
    viejo = _load("informe_resumen.json")
    nuevo = (await client.get("/api/v1/privada/informe/cooperativas/resumen")).json()
    assert _keys(nuevo) == _keys(viejo)
    if viejo["por_tema"] and nuevo["por_tema"]:
        assert _keys(nuevo["por_tema"][0]) == _keys(viejo["por_tema"][0])
