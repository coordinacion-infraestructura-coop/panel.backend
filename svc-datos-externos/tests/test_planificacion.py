"""Datos por localidad para la planificación de svc-privada (ADR-036)."""
from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_gestion.models import ExtGobVisitaGobernador
from app.gobierno.models import ExtGobLocalidad
from app.transferencias.models import ExtTransferencia

URL = "/internal/datos-externos/planificacion/localidades"


def _t(periodo: date, id_geo: str | None, monto: float, concepto: str = "coparticipacion_ley_8663", nombre: str = "X"):
    return ExtTransferencia(
        periodo=periodo, tipo="municipio", id_geo=id_geo, nombre_pdf=nombre,
        departamento_pdf="Colón", concepto=concepto, monto=monto,
    )


async def test_sin_datos(client: AsyncClient):
    r = await client.get(URL)
    assert r.status_code == 200
    assert r.json() == {"coparticipacion_periodo": None, "localidades": []}


async def test_coparticipacion_ultimos_12_meses_y_visita(client: AsyncClient, db_session: AsyncSession):
    db_session.add_all([
        # fuera de la ventana (13 meses antes del último)
        _t(date(2025, 7, 1), "100", 999, nombre="A"),
        # dentro: ago-2025 … jul-2026
        _t(date(2025, 8, 1), "100", 100, nombre="A"),
        _t(date(2026, 7, 1), "100", 200, nombre="A"),
        _t(date(2026, 7, 1), "100", 50, concepto="fasamu", nombre="A"),  # otro concepto: no suma
        _t(date(2026, 7, 1), "200", 70, nombre="B"),
        _t(date(2026, 7, 1), None, 5, nombre="C"),  # sin id_geo: no entra
        ExtGobLocalidad(codigo_indec="140001", nombre_gob="A", departamento_gob="Colón", id_geo="100"),
        ExtGobLocalidad(codigo_indec="140002", nombre_gob="D", departamento_gob="Colón", id_geo="300"),
        ExtGobLocalidad(codigo_indec="140003", nombre_gob="E", departamento_gob="Colón", id_geo=None),
        ExtGobVisitaGobernador(codigo_indec="140001", visitada=True, fecha_ultima=date(2026, 9, 20)),
        ExtGobVisitaGobernador(codigo_indec="140002", visitada=False),
        ExtGobVisitaGobernador(codigo_indec="140003", visitada=True),
    ])
    await db_session.commit()

    body = (await client.get(URL)).json()
    assert body["coparticipacion_periodo"] == {"desde": "2025-08-01", "hasta": "2026-07-01", "meses_ventana": 12}
    por_geo = {f["id_geo"]: f for f in body["localidades"]}
    assert set(por_geo) == {"100", "200", "300"}
    assert por_geo["100"]["coparticipacion_anual"] == {"monto": 300.0, "meses": 2}
    assert por_geo["100"]["visita_gobernador"] == {"visitada": True, "fecha_ultima": "2026-09-20"}
    assert por_geo["200"]["coparticipacion_anual"] == {"monto": 70.0, "meses": 1}
    assert "visita_gobernador" not in por_geo["200"]
    assert por_geo["300"] == {"id_geo": "300", "visita_gobernador": {"visitada": False, "fecha_ultima": None}}


async def test_rollup_territorial_trae_visita_del_gobernador(db_session: AsyncSession):
    """E5g: el rollup para resumen_territorial lleva la visita de la planilla de visitas."""
    from app import rollup

    db_session.add_all([
        ExtGobLocalidad(codigo_indec="140001", nombre_gob="A", departamento_gob="Colón", id_geo="100"),
        ExtGobLocalidad(codigo_indec="140002", nombre_gob="B", departamento_gob="Colón", id_geo="200"),
        ExtGobVisitaGobernador(codigo_indec="140001", visitada=True, fecha_ultima=date(2026, 9, 20)),
    ])
    await db_session.commit()
    por_geo = {r["id_geo"]: r for r in await rollup.rollup_territorial(db_session)}
    assert por_geo["100"]["visita_gobernador"] == {"visitada": True, "fecha_ultima": "2026-09-20"}
    assert por_geo["200"]["visita_gobernador"] is None
