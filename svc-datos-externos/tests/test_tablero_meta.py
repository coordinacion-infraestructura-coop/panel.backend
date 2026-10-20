"""Tablero de Gobierno, Etapa 0 (spec-tablero-gobierno-panel.md §3.3): acceso solo Admin y
Autoridad, y el contenido de GET /api/v1/datos-externos/tablero/meta."""
from datetime import date, datetime, timezone

from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.gobierno.models import ExtGobLocalidad, ExtGobSyncLog
from app.transferencias.models import ExtTransferencia, ExtTransferenciaSyncLog
from tests.conftest import AUTORIDAD_USER, CONSULTA_USER, INVITADO_USER, SUPERVISOR_USER

URL = "/api/v1/datos-externos/tablero/meta"


async def _cargar(db: AsyncSession) -> None:
    db.add_all(
        [
            ExtGobLocalidad(codigo_indec="14014010", nombre_gob="VILLA MARÍA", departamento_gob="GENERAL SAN MARTÍN", tipo="MU", id_geo="140"),
            ExtGobLocalidad(codigo_indec="14007020", nombre_gob="ALTA GRACIA", departamento_gob="SANTA MARÍA", tipo="MU", id_geo="12"),
            ExtGobLocalidad(codigo_indec="14007030", nombre_gob="ANISACATE", departamento_gob="SANTA MARÍA", tipo="CO", id_geo=None),
            ExtGobLocalidad(
                codigo_indec="14099999", nombre_gob="BORRADA", departamento_gob="SANTA MARÍA", tipo="CO",
                deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            ExtGobSyncLog(fuente="nomenclador", estado="ok", filas_upsert=427, corrida_en=datetime(2026, 10, 19, 10, tzinfo=timezone.utc)),
            ExtGobSyncLog(fuente="nomenclador", estado="fallido", filas_upsert=0, corrida_en=datetime(2026, 10, 19, 11, tzinfo=timezone.utc)),
            ExtTransferencia(periodo=date(2025, 12, 1), tipo="municipio", nombre_pdf="X", departamento_pdf="Y", concepto="COPA", monto=1),
            ExtTransferencia(periodo=date(2026, 8, 1), tipo="municipio", nombre_pdf="X", departamento_pdf="Y", concepto="COPA", monto=1),
            ExtTransferenciaSyncLog(periodo=date(2026, 8, 1), tipo="municipio", corrida_en=datetime(2026, 10, 1, tzinfo=timezone.utc)),
            ExtGeoCenso(id="c1", codigo_indec="14014010", categoria="MU", localidad_censo="VILLA MARIA"),
        ]
    )
    await db.commit()


async def test_meta_devuelve_localidades_anios_y_frescura(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    r = await client.get(URL)
    assert r.status_code == 200
    body = r.json()

    # Ordenadas por departamento y nombre; sin las borradas; tipo legible.
    assert [l["nombre"] for l in body["localidades"]] == ["VILLA MARÍA", "ALTA GRACIA", "ANISACATE"]
    assert body["localidades"][2] == {
        "id_geo": None, "codigo_indec": "14007030", "nombre": "ANISACATE", "departamento": "SANTA MARÍA", "tipo": "Comuna",
    }

    assert body["anios"][:3] == sorted(body["anios"][:3], reverse=True)
    assert {2025, 2026} <= set(body["anios"])

    fr = {f["fuente"]: f for f in body["frescura"]}
    assert list(fr) == [
        "nomenclador", "resumen_vista", "copa", "fofindes", "fodemep", "fommep", "empleados",
        "fondo_permanente", "fondo_ambiental", "comunidades_regionales", "transferencias", "censo_2022",
    ]
    assert fr["copa"]["estado"] == "sin_datos"
    # La última corrida manda, aunque haya fallado: el tablero tiene que mostrarlo.
    assert fr["nomenclador"]["estado"] == "fallido"
    assert fr["resumen_vista"]["estado"] == "sin_datos" and fr["resumen_vista"]["ultima_corrida"] is None
    assert fr["transferencias"]["estado"] == "ok" and fr["transferencias"]["ultimo_periodo"] == "2026-08-01"
    assert fr["censo_2022"]["estado"] == "ok" and "1 gobiernos locales" in fr["censo_2022"]["detalle"]


async def test_meta_sin_datos(client: AsyncClient):
    r = await client.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["localidades"] == []
    assert len(body["anios"]) == 1  # solo el año en curso
    assert {f["estado"] for f in body["frescura"]} == {"sin_datos"}


async def test_autoridad_sin_secretaria_puede_leer(client: AsyncClient, as_user):
    as_user(AUTORIDAD_USER)
    assert (await client.get(URL)).status_code == 200


@pytest.mark.parametrize("user", [SUPERVISOR_USER, CONSULTA_USER, INVITADO_USER])
async def test_otros_roles_reciben_403(client: AsyncClient, as_user, user):
    as_user(user)
    r = await client.get(URL)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "PERMISO_INSUFICIENTE"


async def test_sin_token_devuelve_401(client_sin_auth_override: AsyncClient):
    assert (await client_sin_auth_override.get(URL)).status_code == 401
