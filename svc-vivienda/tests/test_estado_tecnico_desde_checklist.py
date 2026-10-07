"""El Estado Técnico de los paneles CC/CH/ML se lee del "Estado del expediente" del checklist
(spec-estado-tecnico-desde-checklist.md)."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico.models import CatalogoEstadoExpediente, CatalogoItemEstado
from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta
from app.geo.models import GeoLocalidad
from app.mi_lugar.models import EstadoML, ProyectoML

CHECKLIST = "/api/v1/vivienda/checklist-tecnico"
CC_BASE = "/api/v1/vivienda/cordon-cuneta"
CH_BASE = "/api/v1/vivienda/cordoba-hogar"
ML_BASE = "/api/v1/vivienda/mi-lugar/proyectos"
RESUMEN = "/api/v1/resumen-territorial"

# Id del catálogo del panel, deliberadamente distinto de los del catálogo del checklist (1-3).
ESTADO_PANEL = 900


@pytest_asyncio.fixture
async def catalogos(db_session: AsyncSession) -> None:
    db_session.add_all([
        CatalogoEstadoExpediente(id=1, label="A ESPERA de DOC.TÉCNICA", orden=0, en_ruta=True),
        CatalogoEstadoExpediente(id=2, label="RECHAZADO por M/C", orden=1, en_ruta=False),
        CatalogoEstadoExpediente(id=3, label="En CURSO en TÉCNICA", orden=2, en_ruta=True),
        CatalogoItemEstado(id=1, label="A ESPERA de DOC.TÉCNICA", orden=0),
        EstadoCordonCuneta(id=ESTADO_PANEL, label="Viejo CC", bg="#fff", text_color="#000", orden=1),
        EstadoCordobaHogar(id=ESTADO_PANEL, label="Viejo CH", bg="#fff", text_color="#000", orden=1),
        EstadoML(id=ESTADO_PANEL, label="Viejo ML", bg="#fff", text_color="#000", orden=1, tipo="exp"),
    ])
    await db_session.flush()


@pytest_asyncio.fixture
async def entidades(db_session: AsyncSession, catalogos: None) -> dict[str, str]:
    """Una fila por programa, las tres con un Estado Técnico viejo cargado en la columna propia."""
    ids = {p: str(uuid.uuid4()) for p in ("cc", "ch", "ml")}
    db_session.add_all([
        GeoLocalidad(id_geo="g1", departamento="Santa María", localidad="Alta Gracia", activo=True),
        MunicipioCordonCuneta(
            id=ids["cc"], orden=1, municipio="Alta Gracia", departamento="Santa María",
            etecnico=ESTADO_PANEL,
        ),
        LocalidadCordobaHogar(
            id=ids["ch"], orden=1, localidad="Alta Gracia", departamento="Santa María",
            etecnico=ESTADO_PANEL,
        ),
        ProyectoML(
            id=ids["ml"], tipo="exp", nombre="Predio Norte", localidad_nombre="Alta Gracia",
            departamento="Santa María", etecnico=ESTADO_PANEL,
        ),
    ])
    await db_session.flush()
    return ids


async def _etecnico_en_panel(client: AsyncClient, programa: str, entidad_id: str) -> int | None:
    if programa == "cc":
        filas = (await client.get(CC_BASE)).json()["municipios"]
    elif programa == "ch":
        filas = (await client.get(CH_BASE)).json()["localidades"]
    else:
        filas = (await client.get(ML_BASE)).json()
    return next(f for f in filas if f["id"] == entidad_id)["etecnico"]


def _url_entidad(programa: str, entidad_id: str) -> str:
    return f"{ {'cc': CC_BASE, 'ch': CH_BASE, 'ml': ML_BASE}[programa] }/{entidad_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", ["cc", "ch", "ml"])
async def test_sin_estado_en_checklist_el_panel_muestra_vacio(
    client: AsyncClient, entidades: dict[str, str], programa: str
):
    """La columna vieja tiene un valor, pero ya no se lee."""
    assert await _etecnico_en_panel(client, programa, entidades[programa]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", ["cc", "ch", "ml"])
async def test_cambio_en_checklist_se_refleja_en_el_panel(
    client: AsyncClient, entidades: dict[str, str], programa: str
):
    entidad_id = entidades[programa]
    r = await client.patch(f"{CHECKLIST}/{programa}/{entidad_id}", json={"estado_expediente_id": 3})
    assert r.status_code == 200

    assert await _etecnico_en_panel(client, programa, entidad_id) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("programa,modelo", [
    ("cc", MunicipioCordonCuneta), ("ch", LocalidadCordobaHogar), ("ml", ProyectoML),
])
async def test_el_panel_no_puede_cambiar_el_tecnico(
    client: AsyncClient, db_session: AsyncSession, entidades: dict[str, str], programa: str, modelo
):
    entidad_id = entidades[programa]
    await client.patch(f"{CHECKLIST}/{programa}/{entidad_id}", json={"estado_expediente_id": 1})

    r = await client.patch(_url_entidad(programa, entidad_id), json={"etecnico": 3, "obs": "nota"})
    assert r.status_code == 200
    assert r.json()["etecnico"] == 1  # sigue mandando el checklist
    assert r.json()["obs"] == "nota"  # el resto del PATCH sí se aplica

    columna = (await db_session.execute(select(modelo.etecnico).where(modelo.id == entidad_id))).scalar_one()
    assert columna == ESTADO_PANEL  # la columna vieja queda congelada

    hist = (await client.get(f"{_url_entidad(programa, entidad_id)}/historial")).json()
    assert [h["campo"] for h in hist] == ["etecnico_checklist"]


@pytest.mark.asyncio
async def test_alta_en_panel_ignora_etecnico(client: AsyncClient, catalogos: None):
    r = await client.post(CC_BASE, json={"municipio": "Pueblo Nuevo", "departamento": "Test", "etecnico": 3})
    assert r.status_code == 201
    assert r.json()["etecnico"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", ["cc", "ch", "ml"])
async def test_historial_del_panel_incluye_cambios_del_checklist(
    client: AsyncClient, entidades: dict[str, str], programa: str
):
    entidad_id = entidades[programa]
    for estado in (1, 3, 2):
        await client.patch(f"{CHECKLIST}/{programa}/{entidad_id}", json={"estado_expediente_id": estado})

    hist = (await client.get(f"{_url_entidad(programa, entidad_id)}/historial")).json()
    tecnico = [h for h in hist if h["campo"] == "etecnico_checklist"]
    transiciones = {(h["estado_anterior_id"], h["estado_nuevo_id"]) for h in tecnico}
    assert transiciones == {(None, 1), (1, 3), (3, 2)}
    assert all(h["created_by"] == "admin@test.com" for h in tecnico)


@pytest.mark.asyncio
async def test_historial_mezcla_cambios_del_panel_y_del_checklist(
    client: AsyncClient, db_session: AsyncSession, entidades: dict[str, str]
):
    db_session.add(EstadoCordonCuneta(id=901, label="Otro", bg="#fff", text_color="#000", orden=2))
    await db_session.flush()
    mid = entidades["cc"]
    await client.patch(f"{CC_BASE}/{mid}", json={"ejuridico": 901})
    await client.patch(f"{CHECKLIST}/cc/{mid}", json={"estado_expediente_id": 3})

    hist = (await client.get(f"{CC_BASE}/{mid}/historial")).json()
    assert {h["campo"] for h in hist} == {"ejuridico", "etecnico_checklist"}


@pytest.mark.asyncio
async def test_resumen_territorial_usa_el_estado_del_checklist(
    client: AsyncClient, entidades: dict[str, str]
):
    await client.patch(f"{CHECKLIST}/cc/{entidades['cc']}", json={"estado_expediente_id": 3})

    payload = (await client.post(f"{RESUMEN}/actualizar")).json()["payload"]
    programas = next(l for l in payload["localidades"] if l["localidad"] == "Alta Gracia")["programas"]
    cc = next(p for p in programas if p["programa"] == "cordon_cuneta")
    ch = next(p for p in programas if p["programa"] == "cordoba_hogar")
    assert cc["subestados"]["tecnico"] == "En CURSO en TÉCNICA"
    assert ch["subestados"]["tecnico"] is None  # tenía estado viejo en la columna; ya no se usa
