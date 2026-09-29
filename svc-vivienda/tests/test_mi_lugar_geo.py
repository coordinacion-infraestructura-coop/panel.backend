"""Resolución de localidad_id/localidad_match_tipo en Mi Lugar (ADR-024) —
cierra el último gap de "resolver-on-write" que ya tenían cordon_cuneta y
cordoba_hogar. Ver docs/files/spec-normalizacion-localidades.md §4.10."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

BASE = "/api/v1/vivienda/mi-lugar/proyectos"


@pytest_asyncio.fixture
async def geo_san_jose(db_session: AsyncSession):
    from app.geo.models import GeoLocalidad
    db_session.add(GeoLocalidad(id_geo="777", departamento="Tulumba", localidad="San José", activo=True))
    await db_session.flush()


@pytest.mark.asyncio
async def test_crear_proyecto_ml_resuelve_localidad_id(client: AsyncClient, geo_san_jose):
    r = await client.post(BASE, json={
        "tipo": "exp",
        "nombre": "Lote 1",
        "localidad_nombre": "San José",
        "departamento": "Tulumba",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["localidad_id"] == "777"
    assert data["localidad_match_tipo"] == "exacto"


@pytest.mark.asyncio
async def test_crear_proyecto_ml_ignora_localidad_id_enviado_por_el_cliente(client: AsyncClient, geo_san_jose):
    """localidad_id siempre se resuelve server-side, nunca se confía en el
    valor que mande el cliente (mismo criterio que cordon_cuneta/cordoba_hogar)."""
    r = await client.post(BASE, json={
        "tipo": "exp",
        "nombre": "Lote 1",
        "localidad_nombre": "San José",
        "departamento": "Tulumba",
        "localidad_id": "999-inventado",
    })
    assert r.status_code == 201
    assert r.json()["localidad_id"] == "777"


@pytest.mark.asyncio
async def test_crear_proyecto_ml_sin_match_no_bloquea_alta(client: AsyncClient):
    r = await client.post(BASE, json={
        "tipo": "exp",
        "nombre": "Lote 1",
        "localidad_nombre": "Localidad Sin Padrón",
        "departamento": "Capital",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["localidad_id"] is None
    assert data["localidad_match_tipo"] == "sin_match"


@pytest.mark.asyncio
async def test_actualizar_proyecto_ml_recalcula_localidad_id(client: AsyncClient, geo_san_jose):
    r = await client.post(BASE, json={
        "tipo": "exp",
        "nombre": "Lote 1",
        "localidad_nombre": "Localidad Sin Padrón",
        "departamento": "Capital",
    })
    proyecto_id = r.json()["id"]
    assert r.json()["localidad_id"] is None

    r2 = await client.patch(f"{BASE}/{proyecto_id}", json={
        "localidad_nombre": "San José",
        "departamento": "Tulumba",
    })
    assert r2.status_code == 200
    assert r2.json()["localidad_id"] == "777"
    assert r2.json()["localidad_match_tipo"] == "exacto"


@pytest.mark.asyncio
async def test_actualizar_proyecto_ml_sin_cambiar_localidad_no_recalcula(client: AsyncClient, geo_san_jose):
    r = await client.post(BASE, json={
        "tipo": "exp",
        "nombre": "Lote 1",
        "localidad_nombre": "San José",
        "departamento": "Tulumba",
    })
    proyecto_id = r.json()["id"]

    r2 = await client.patch(f"{BASE}/{proyecto_id}", json={"responsable": "Nuevo Responsable"})
    assert r2.status_code == 200
    assert r2.json()["localidad_id"] == "777"
    assert r2.json()["localidad_match_tipo"] == "exacto"
