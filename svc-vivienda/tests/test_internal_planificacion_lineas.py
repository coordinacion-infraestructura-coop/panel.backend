"""`GET /internal/planificacion/lineas` — lectura IAM-only para la planificación de svc-privada
(ADR-036). No escribe nada; agrupa por `id_geo` del lado de svc-privada."""
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta
from app.database import get_db
from app.main import app
from app.mi_lugar.models import ProyectoML


@pytest.fixture
async def c(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cli:
        yield cli
    app.dependency_overrides.clear()


async def test_cc_lineas_por_id_geo(c, db_session: AsyncSession):
    db_session.add(EstadoCordonCuneta(id=7, label="EN OBRA", bg="#000000", text_color="#ffffff", orden=1))
    db_session.add_all([
        MunicipioCordonCuneta(id=str(uuid.uuid4()), municipio="Embalse", localidad_id="1", ok_gob="SI",
                              estado_general=7, monto=200_000_000),
        MunicipioCordonCuneta(id=str(uuid.uuid4()), municipio="Embalse II", localidad_id="1", ok_gob="NO"),
        MunicipioCordonCuneta(id=str(uuid.uuid4()), municipio="Sin vínculo", localidad_id=None),
        MunicipioCordonCuneta(id=str(uuid.uuid4()), municipio="Borrada", localidad_id="2",
                              deleted_at=date(2026, 1, 1)),
    ])
    await db_session.flush()

    r = await c.get("/internal/planificacion/lineas", params={"programa": "cordon_cuneta"})
    assert r.status_code == 200
    body = r.json()
    assert body["sin_id_geo"] == 1
    assert len(body["lineas"]) == 2 and {li["id_geo"] for li in body["lineas"]} == {"1"}
    con_estado = next(li for li in body["lineas"] if li["estado_general"])
    assert con_estado["estado_general"]["label"] == "EN OBRA"
    assert con_estado["ok_gob"] is True and con_estado["monto"] == 200_000_000
    # CC no tiene la firma como dato propio: queda null, nunca se infiere de ok_gob
    assert all(li["convenio_firmado"] is None and li["fecha_firma_convenio"] is None for li in body["lineas"])
    assert next(li for li in body["lineas"] if not li["estado_general"])["ok_gob"] is False


async def test_ch_trae_convenio_firmado(c, db_session: AsyncSession):
    db_session.add(EstadoCordobaHogar(id=9, label="Convenio Firmado", bg="#E0F7FA", text_color="#006064", orden=8))
    db_session.add(LocalidadCordobaHogar(
        id=str(uuid.uuid4()), orden=1, localidad="Saira", localidad_id="25", estado_general=9,
        convenio_firmado=True, fecha_firma_convenio=date(2026, 6, 23),
    ))
    await db_session.flush()
    linea = (await c.get("/internal/planificacion/lineas", params={"programa": "cordoba_hogar"})).json()["lineas"][0]
    assert linea["convenio_firmado"] is True and linea["fecha_firma_convenio"] == "2026-06-23"


async def test_ml_y_programa_desconocido(c, db_session: AsyncSession):
    db_session.add(ProyectoML(id=str(uuid.uuid4()), tipo="exp", nombre="Predio", localidad_nombre="Villa María",
                              localidad_id="300"))
    await db_session.flush()
    body = (await c.get("/internal/planificacion/lineas", params={"programa": "mi_lugar"})).json()
    assert [li["id_geo"] for li in body["lineas"]] == ["300"]
    r = await c.get("/internal/planificacion/lineas", params={"programa": "gas_pit"})
    assert r.status_code == 422
