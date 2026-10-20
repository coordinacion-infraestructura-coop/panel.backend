"""ATP Compromisos para el Tablero de Gobierno (spec-tablero-gobierno-panel.md, Etapa 1)."""
from datetime import date, datetime, timezone

from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.atp.models import AtpCompromiso, AtpCronogramaPago
from app.atp.tablero import estado_pago
from tests.conftest import AUTORIDAD_SIN_SECRETARIA_USER, CONSULTA_USER, INVITADO_USER, OPERADOR_USER

URL = "/api/v1/gralgob/tablero/atp-compromisos"
AHORA = datetime.now(timezone.utc)


def _c(i: int, **kw) -> AtpCompromiso:
    base = dict(
        id=f"c{i}", sheet_row_number=10 + i, departamento="CALAMUCHITA", localidad="EMBALSE", id_geo="10",
        ministerio_destino="Gobierno", fecha_anuncio=date(2026, 1, i), derivado=False, monto=100.0,
        last_synced_at=AHORA,
    )
    base.update(kw)
    return AtpCompromiso(**base)


async def _cargar(db: AsyncSession) -> None:
    db.add_all([
        _c(1),  # pagado completo (cronograma negativo, como la planilla)
        _c(2, monto=200.0, ministerio_destino="Salud"),  # parcial
        _c(3, monto=50.0, id_geo="20", departamento="PUNILLA", localidad="COSQUÍN", derivado=True),  # pendiente
        _c(4, monto=None, id_geo=None, localidad="SIN VINCULAR"),  # sin monto
    ])
    db.add_all([
        AtpCronogramaPago(compromiso_id="c1", periodo=date(2026, 2, 1), monto=-60),
        AtpCronogramaPago(compromiso_id="c1", periodo=date(2026, 3, 1), monto=-40),
        AtpCronogramaPago(compromiso_id="c2", periodo=date(2026, 3, 1), monto=-50),
    ])
    await db.commit()


@pytest.mark.parametrize(
    "monto,pagado,esperado",
    [(100, 0, "Pendiente"), (100, 40, "Parcial"), (100, 100, "Pagado"), (100, 120, "Pagado"), (None, 10, "Sin dato"), (0, 0, "Sin dato")],
)
def test_estado_pago(monto, pagado, esperado):
    assert estado_pago(monto, pagado) == esperado


async def test_provincia(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    r = await client.get(URL)
    assert r.status_code == 200
    b = r.json()
    assert b["kpis"] == {"localidades": 3, "compromisos": 4, "derivados": 1, "monto": 350.0, "pagado": 150.0, "saldo": 200.0}
    assert [(g["clave"], g["cantidad"]) for g in b["por_estado"]] == [("Pagado", 1), ("Parcial", 1), ("Pendiente", 1), ("Sin dato", 1)]
    # De mayor a menor monto.
    assert b["por_ministerio"] == [
        {"clave": "Salud", "cantidad": 1, "monto": 200.0, "pagado": 50.0},
        {"clave": "Gobierno", "cantidad": 3, "monto": 150.0, "pagado": 100.0},
    ]
    # Más recientes primero; pagado en valor absoluto.
    assert [f["id"] for f in b["filas"]] == ["c4", "c3", "c2", "c1"]
    assert b["filas"][3]["pagado"] == 100.0 and b["filas"][3]["estado"] == "Pagado"
    assert b["estado_sincronizacion"] == "sin_datos"


async def test_filtro_por_id_geo(client: AsyncClient, db_session: AsyncSession):
    await _cargar(db_session)
    b = (await client.get(URL, params=[("id_geo", "10")])).json()
    assert b["kpis"]["compromisos"] == 2 and b["kpis"]["monto"] == 300.0
    b = (await client.get(URL, params=[("id_geo", "10"), ("id_geo", "20")])).json()
    assert b["kpis"]["compromisos"] == 3
    assert [g["clave"] for g in b["por_departamento"]] == ["CALAMUCHITA", "PUNILLA"]


async def test_autoridad_sin_secretaria_gralgob_puede_leer(client: AsyncClient, as_user):
    as_user(AUTORIDAD_SIN_SECRETARIA_USER)
    assert (await client.get(URL)).status_code == 200


@pytest.mark.parametrize("user", [OPERADOR_USER, CONSULTA_USER, INVITADO_USER])
async def test_otros_roles_403_aunque_tengan_gralgob(client: AsyncClient, as_user, user):
    as_user(user)
    assert (await client.get(URL)).status_code == 403
