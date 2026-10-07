"""CC / CH / Mi Lugar guardan el nombre del padrón oficial cuando hay vínculo
(ADR-026 — cambia spec-normalizacion-localidades.md §2.6). Sin vínculo, el
texto que llegó se conserva (loteos de Mi Lugar por barrio de Capital)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

CC = "/api/v1/vivienda/cordon-cuneta"
CH = "/api/v1/vivienda/cordoba-hogar"
ML = "/api/v1/vivienda/mi-lugar/proyectos"


@pytest_asyncio.fixture
async def padron(db_session: AsyncSession):
    from app.geo.models import GeoLocalidad
    db_session.add_all([
        GeoLocalidad(id_geo="88", departamento="JUÁREZ CELMAN", localidad="CHARRAS (VILLA COLON)", activo=True),
        GeoLocalidad(id_geo="392", departamento="RÍO PRIMERO", localidad="MONTE CRISTO", activo=True),
    ])
    await db_session.flush()


@pytest.mark.asyncio
async def test_cc_alta_guarda_el_nombre_oficial(client: AsyncClient, padron):
    r = await client.post(CC, json={"municipio": "Charras", "departamento": "Juárez Celman"})
    assert r.status_code == 201
    data = r.json()
    assert data["localidad_id"] == "88"
    assert data["municipio"] == "CHARRAS (VILLA COLON)"
    assert data["departamento"] == "JUÁREZ CELMAN"


@pytest.mark.asyncio
async def test_cc_edicion_guarda_el_nombre_oficial(client: AsyncClient, padron):
    alta = await client.post(CC, json={"municipio": "Pueblo Sin Padrón", "departamento": "Capital"})
    assert alta.json()["localidad_id"] is None
    assert alta.json()["municipio"] == "Pueblo Sin Padrón"  # sin vínculo: queda el texto

    r = await client.patch(f"{CC}/{alta.json()['id']}", json={"municipio": "monte cristo", "departamento": "Río Primero"})
    assert r.status_code == 200
    data = r.json()
    assert data["localidad_id"] == "392"
    assert data["municipio"] == "MONTE CRISTO"
    assert data["departamento"] == "RÍO PRIMERO"


@pytest.mark.asyncio
async def test_ch_alta_guarda_el_nombre_oficial(client: AsyncClient, padron):
    r = await client.post(CH, json={"localidad": "Charras", "departamento": "Juárez Celman"})
    assert r.status_code == 201
    data = r.json()
    assert data["localidad"] == "CHARRAS (VILLA COLON)"
    assert data["departamento"] == "JUÁREZ CELMAN"


@pytest.mark.asyncio
async def test_ml_con_vinculo_guarda_el_nombre_oficial_y_corrige_el_departamento(client: AsyncClient, padron):
    # el padrón tiene una sola "Monte Cristo": un departamento mal cargado no impide el vínculo
    r = await client.post(ML, json={
        "tipo": "exp", "nombre": "Lote 1", "localidad_nombre": "Monte Cristo", "departamento": "Colón",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["localidad_id"] == "392"
    assert data["localidad_nombre"] == "MONTE CRISTO"
    assert data["departamento"] == "RÍO PRIMERO"


@pytest.mark.asyncio
async def test_ml_barrio_sin_vinculo_conserva_el_texto(client: AsyncClient, padron):
    r = await client.post(ML, json={"tipo": "prov", "nombre": "Loteo", "localidad_nombre": "Barrio Chingolo"})
    assert r.status_code == 201
    data = r.json()
    assert data["localidad_id"] is None
    assert data["localidad_nombre"] == "Barrio Chingolo"
