"""Tablero de Gobierno, Etapa 1: cálculos puros e /inicio y /transferencias/{seccion}."""
from datetime import date

from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_censo.models import ExtGeoCenso
from app.gobierno.models import ExtGobLocalidad
from app.tablero import aggregations as ag
from app.transferencias.models import ExtTransferencia
from tests.conftest import CONSULTA_USER

# ── Cálculos puros ──────────────────────────────────────────────────────────────


def test_serie_mensual_distingue_sin_dato_de_cero():
    s = ag.serie_mensual([(date(2026, 1, 1), 10), (date(2026, 1, 1), 5), (date(2026, 3, 1), 0), (date(2025, 2, 1), 99)], 2026)
    assert s[:4] == [15.0, None, 0.0, None]
    assert s[4:] == [None] * 8


def test_ultimo_mes_acumulado_y_variacion():
    s = [10.0, None, 30.0] + [None] * 9
    assert ag.ultimo_mes_con_dato(s) == 2
    assert ag.ultimo_mes_con_dato([None] * 12) is None
    assert ag.acumulado(s, 2) == 40.0 and ag.acumulado(s, 0) == 10.0 and ag.acumulado(s, None) == 0.0
    assert ag.variacion(120, 100) == pytest.approx(0.2)
    assert ag.variacion(5, 0) is None and ag.variacion(5, None) is None


def test_por_habitante():
    assert ag.por_habitante(1000, 4) == 250
    assert ag.por_habitante(1000, 0) is None and ag.por_habitante(1000, None) is None


# ── Endpoints ───────────────────────────────────────────────────────────────────


def _tr(periodo, concepto, monto, id_geo):
    return ExtTransferencia(periodo=periodo, tipo="municipio", id_geo=id_geo, nombre_pdf=f"LOC {id_geo}", departamento_pdf="Y", concepto=concepto, monto=monto)


async def _cargar(db: AsyncSession) -> None:
    db.add_all([
        ExtGobLocalidad(codigo_indec="A", nombre_gob="LOC A", departamento_gob="D1", tipo="MU", id_geo="1", poblacion_2022_gob=999),
        ExtGobLocalidad(codigo_indec="B", nombre_gob="LOC B", departamento_gob="D1", tipo="CO", id_geo="2", poblacion_2022_gob=50),
        ExtGobLocalidad(codigo_indec="C", nombre_gob="LOC C", departamento_gob="D2", tipo="MU", id_geo="3"),
        ExtGeoCenso(id="c-a", codigo_indec="A", categoria="MU", localidad_censo="LOC A", poblacion_2022=100),
        ExtGeoCenso(id="c-c", codigo_indec="C", categoria="MU", localidad_censo="LOC C", poblacion_2022=200),
        _tr(date(2026, 1, 1), "coparticipacion_ley_8663", 1000, "1"),
        _tr(date(2026, 2, 1), "coparticipacion_ley_8663", 2000, "1"),
        _tr(date(2026, 2, 1), "fofindes", 300, "2"),
        _tr(date(2026, 2, 1), "total", 99999, "1"),  # el "total" del PDF nunca se suma
        _tr(date(2026, 2, 1), "coparticipacion_ley_8663", 500, None),  # sin vínculo al padrón
        _tr(date(2025, 1, 1), "coparticipacion_ley_8663", 800, "1"),
        _tr(date(2025, 2, 1), "coparticipacion_ley_8663", 1700, "1"),
        _tr(date(2025, 3, 1), "coparticipacion_ley_8663", 9000, "1"),
    ])
    await db.commit()


async def test_inicio_provincia(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    b = (await client.get("/api/v1/datos-externos/tablero/inicio", params={"anio": 2026})).json()
    # Población: Censo primero, Vista de Gobierno si falta (B).
    assert b["kpis"] == {"localidades": 3, "municipios": 2, "comunas": 1, "poblacion": 350, "transferido": 3800.0, "por_habitante": pytest.approx(3800 / 350)}
    assert b["periodo_hasta"] == "2026-02-01"
    d1 = next(d for d in b["por_departamento"] if d["departamento"] == "D1")
    # Por departamento solo lo vinculado (los 500 sin id_geo no entran).
    assert d1 == {"departamento": "D1", "localidades": 2, "poblacion": 150, "transferido": 3300.0, "por_habitante": 22.0}


async def test_inicio_filtrado_por_localidad(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    b = (await client.get("/api/v1/datos-externos/tablero/inicio", params=[("anio", 2026), ("codigo_indec", "B")])).json()
    assert b["kpis"]["localidades"] == 1 and b["kpis"]["transferido"] == 300.0 and b["kpis"]["poblacion"] == 50


async def test_coparticipacion_compara_contra_mismo_periodo_del_anio_anterior(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    b = (await client.get("/api/v1/datos-externos/tablero/transferencias/coparticipacion", params={"anio": 2026})).json()
    assert b["total_anio"] == 3500.0  # incluye los 500 sin vínculo: coincide con el PDF
    assert b["ultimo_periodo"] == "2026-02-01" and b["ultimo_mes"] == 2500.0
    assert b["acumulado_anterior"] == 2500.0  # ene + feb 2025, no marzo
    assert b["variacion"] == pytest.approx(0.4)
    assert b["mensual"][:3] == [1000.0, 2500.0, None]
    assert b["mensual_anterior"][:3] == [800.0, 1700.0, 9000.0]
    assert [c["concepto"] for c in b["por_concepto"]] == ["coparticipacion_ley_8663", "fofindes"]
    assert b["localidades"] == 1


async def test_fofindes_filtrado(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    url = "/api/v1/datos-externos/tablero/transferencias/fofindes"
    assert (await client.get(url, params=[("anio", 2026), ("codigo_indec", "B")])).json()["total_anio"] == 300.0
    b = (await client.get(url, params=[("anio", 2026), ("codigo_indec", "A")])).json()
    assert b["total_anio"] == 0.0 and b["ultimo_periodo"] is None and b["variacion"] is None


async def test_seccion_inexistente_404(client: AsyncClient):
    r = await client.get("/api/v1/datos-externos/tablero/transferencias/fasamu", params={"anio": 2026})
    assert r.status_code == 404


async def test_anio_obligatorio(client: AsyncClient):
    assert (await client.get("/api/v1/datos-externos/tablero/inicio")).status_code == 422


@pytest.mark.parametrize("url", ["/api/v1/datos-externos/tablero/inicio", "/api/v1/datos-externos/tablero/transferencias/coparticipacion"])
async def test_solo_admin_y_autoridad(client: AsyncClient, as_user, url):
    as_user(CONSULTA_USER)
    assert (await client.get(url, params={"anio": 2026})).status_code == 403
