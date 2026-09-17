"""Tests del informe "Localidades por Departamento"
(spec-informe-localidades-departamento.md): cruce on-the-fly entre
`viv_geo_localidades`, Cordón Cuneta, Córdoba Hogar y habitantes (federados
desde svc-privada)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.cordoba_hogar.models import LocalidadCordobaHogar
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.geo.matching import candidatos_localidad
from app.geo.models import GeoLocalidad

BASE = "/api/v1/vivienda/informe-localidades"


def _seed_geo(db_session):
    db_session.add_all([
        GeoLocalidad(id_geo="g1", departamento="Capital", localidad="Córdoba Capital", activo=True),
        GeoLocalidad(id_geo="g2", departamento="Colón", localidad="Jesús María", activo=True),
        GeoLocalidad(id_geo="g3", departamento="Colón", localidad="Sin Datos", activo=True),
        GeoLocalidad(id_geo="g4", departamento="Colón", localidad="Inactiva", activo=False),
    ])


@pytest.mark.asyncio
async def test_informe_cruza_cc_ch_y_marca_null_donde_no_hay_dato(client, db_session):
    _seed_geo(db_session)
    db_session.add(MunicipioCordonCuneta(
        id=str(uuid.uuid4()), orden=1, municipio="CORDOBA CAPITAL", departamento="capital",
        cordon_cuneta_ml=500, adoquinado_m2=200,
    ))
    db_session.add(LocalidadCordobaHogar(
        id=str(uuid.uuid4()), orden=1, localidad="jesus maria", departamento="COLON",
        cantidad_casas=30,
    ))
    await db_session.flush()

    with patch(
        "app.informe_localidades.service.fetch_habitantes_privada",
        new=AsyncMock(return_value={}),
    ):
        resp = await client.get(BASE)
    assert resp.status_code == 200
    filas = {(f["departamento"], f["localidad"]): f for f in resp.json()}

    # localidad inactiva no debe aparecer
    assert ("Colón", "Inactiva") not in filas

    cc = filas[("Capital", "Córdoba Capital")]
    assert cc["tiene_cordon_cuneta"] is True
    assert cc["ml_cordon_cuneta"] == "500.00" or float(cc["ml_cordon_cuneta"]) == 500.0
    assert cc["tiene_viviendas"] is False
    assert cc["cantidad_viviendas"] is None
    assert cc["cant_habitantes"] is None

    ch = filas[("Colón", "Jesús María")]
    assert ch["tiene_viviendas"] is True
    assert ch["cantidad_viviendas"] == 30
    assert ch["tiene_cordon_cuneta"] is False
    assert ch["ml_cordon_cuneta"] is None

    sin_datos = filas[("Colón", "Sin Datos")]
    assert sin_datos["tiene_cordon_cuneta"] is False
    assert sin_datos["tiene_viviendas"] is False
    assert sin_datos["cant_habitantes"] is None


@pytest.mark.asyncio
async def test_informe_matching_insensible_a_mayusculas_y_acentos(client, db_session):
    _seed_geo(db_session)
    db_session.add(MunicipioCordonCuneta(
        id=str(uuid.uuid4()), orden=1, municipio="jesus maria", departamento="colon",
        cordon_cuneta_ml=None,
    ))
    await db_session.flush()

    with patch(
        "app.informe_localidades.service.fetch_habitantes_privada",
        new=AsyncMock(return_value={}),
    ):
        resp = await client.get(BASE)
    fila = next(f for f in resp.json() if f["localidad"] == "Jesús María")
    assert fila["tiene_cordon_cuneta"] is True


@pytest.mark.asyncio
async def test_informe_ignora_registros_borrados(client, db_session):
    from datetime import datetime, timezone

    _seed_geo(db_session)
    db_session.add(MunicipioCordonCuneta(
        id=str(uuid.uuid4()), orden=1, municipio="CORDOBA CAPITAL", departamento="capital",
        cordon_cuneta_ml=500, deleted_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()

    with patch(
        "app.informe_localidades.service.fetch_habitantes_privada",
        new=AsyncMock(return_value={}),
    ):
        resp = await client.get(BASE)
    fila = next(f for f in resp.json() if f["localidad"] == "Córdoba Capital")
    assert fila["tiene_cordon_cuneta"] is False
    assert fila["ml_cordon_cuneta"] is None


@pytest.mark.asyncio
async def test_informe_usa_habitantes_devueltos_por_privada(client, db_session):
    _seed_geo(db_session)
    await db_session.flush()

    with patch(
        "app.informe_localidades.service.fetch_habitantes_privada",
        new=AsyncMock(return_value={("capital", "cordoba capital"): 350000}),
    ):
        resp = await client.get(BASE)
    fila = next(f for f in resp.json() if f["localidad"] == "Córdoba Capital")
    assert fila["cant_habitantes"] == 350000


@pytest.mark.asyncio
async def test_fetch_habitantes_privada_default_deshabilitado_da_diccionario_vacio():
    """Sin parchear nada: `privada_fetch_enabled=False` por default → no pega a la red."""
    from app.informe_localidades.service import fetch_habitantes_privada

    assert await fetch_habitantes_privada() == {}


def test_candidatos_localidad_extrae_alias_entre_parentesis_y_guion():
    assert "holmberg" in candidatos_localidad("Santa Catalina (Est. Holmberg)")
    assert "santa catalina" in candidatos_localidad("Santa Catalina (Est. Holmberg)")
    assert "maria elena" in candidatos_localidad("Elena - Maria Elena")
    assert candidatos_localidad(None) == set()
    assert candidatos_localidad("") == set()


@pytest.mark.asyncio
async def test_informe_matchea_habitantes_por_alias_de_localidad(client, db_session):
    """Geo con alias entre paréntesis debe encontrar habitantes aunque
    Privada lo devuelva bajo el alias corto (no el nombre completo) — mismo
    caso real que resolvió cargar_habitantes_censo2022.py con
    "Santa Catalina Holmberg"."""
    db_session.add(GeoLocalidad(
        id_geo="g5", departamento="Río Cuarto",
        localidad="Santa Catalina (Est. Holmberg)", activo=True,
    ))
    await db_session.flush()

    with patch(
        "app.informe_localidades.service.fetch_habitantes_privada",
        new=AsyncMock(return_value={("rio cuarto", "holmberg"): 5057}),
    ):
        resp = await client.get(BASE)
    fila = next(f for f in resp.json() if f["localidad"] == "Santa Catalina (Est. Holmberg)")
    assert fila["cant_habitantes"] == 5057


@pytest.mark.asyncio
async def test_informe_requiere_rol_de_lectura(client_invitado):
    resp = await client_invitado.get(BASE)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_tecnico_dgv_puede_ver_el_informe(client_tecnico_dgv, db_session):
    _seed_geo(db_session)
    await db_session.flush()
    with patch(
        "app.informe_localidades.service.fetch_habitantes_privada",
        new=AsyncMock(return_value={}),
    ):
        resp = await client_tecnico_dgv.get(BASE)
    assert resp.status_code == 200
