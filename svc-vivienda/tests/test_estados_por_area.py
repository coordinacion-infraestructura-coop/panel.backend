"""Estados de CC / CH / ML: un listado por área (spec-vivienda-estados-por-area.md)."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta
from app.mi_lugar.models import EstadoML, ProyectoML

BASES = {
    "cc": "/api/v1/vivienda/cordon-cuneta",
    "ch": "/api/v1/vivienda/cordoba-hogar",
    "ml": "/api/v1/vivienda/mi-lugar",
}
ENTIDAD = {"cc": BASES["cc"], "ch": BASES["ch"], "ml": f"{BASES['ml']}/proyectos"}
NUEVO = {"label": "En revisión", "bg": "#fff", "text_color": "#000", "orden": 1}

# Un estado por listado, mismo id en los tres programas.
JURIDICO, FINANCIERO, GENERAL = 501, 502, 503


@pytest_asyncio.fixture
async def entidades(db_session: AsyncSession) -> dict[str, str]:
    for modelo, extra in ((EstadoCordonCuneta, {}), (EstadoCordobaHogar, {}), (EstadoML, {"tipo": "exp"})):
        for id_, dim in ((JURIDICO, "juridico"), (FINANCIERO, "financiero"), (GENERAL, "general")):
            db_session.add(modelo(id=id_, label=dim, bg="#fff", text_color="#000", orden=1, dimension=dim, **extra))
    ids = {p: str(uuid.uuid4()) for p in BASES}
    db_session.add_all([
        MunicipioCordonCuneta(id=ids["cc"], orden=1, municipio="Pueblo", departamento="Depto"),
        LocalidadCordobaHogar(id=ids["ch"], orden=1, localidad="Pueblo", departamento="Depto"),
        ProyectoML(id=ids["ml"], tipo="exp", nombre="Predio", localidad_nombre="Pueblo", departamento="Depto"),
    ])
    await db_session.flush()
    return ids


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", list(BASES))
async def test_alta_de_estado_exige_listado(client: AsyncClient, programa: str):
    base = BASES[programa]
    assert (await client.post(f"{base}/estados", json=NUEVO)).status_code == 422
    assert (await client.post(f"{base}/estados", json={**NUEVO, "dimension": "tecnico_anterior"})).status_code == 422

    r = await client.post(f"{base}/estados", json={**NUEVO, "dimension": "financiero"})
    assert r.status_code == 201, r.text
    assert r.json()["dimension"] == "financiero"
    assert "aplica_juridico" not in r.json()

    # El listado no se cambia después del alta.
    r = await client.patch(f"{base}/estados/{r.json()['id']}", json={"label": "Otro", "dimension": "juridico"})
    assert r.status_code == 200
    assert (r.json()["label"], r.json()["dimension"]) == ("Otro", "financiero")


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", list(BASES))
async def test_cada_columna_acepta_solo_estados_de_su_listado(
    client: AsyncClient, entidades: dict[str, str], programa: str
):
    url = f"{ENTIDAD[programa]}/{entidades[programa]}"
    for campo, otro in (("ejuridico", FINANCIERO), ("efinanciero", GENERAL), ("estado_general", JURIDICO)):
        r = await client.patch(url, json={campo: otro})
        assert r.status_code == 422, (campo, r.text)
        assert r.json()["detail"]["code"] == "ESTADO_DE_OTRO_LISTADO"

    r = await client.patch(url, json={"ejuridico": JURIDICO, "efinanciero": FINANCIERO, "estado_general": GENERAL})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", list(BASES))
async def test_editar_no_valida_los_estados_que_no_cambian(
    client: AsyncClient, db_session: AsyncSession, entidades: dict[str, str], programa: str
):
    """El formulario reenvía todos los estados: un valor previo fuera de su listado (o huérfano)
    no bloquea la edición; cambiarlo a uno de otro listado, sí."""
    modelo = {"cc": MunicipioCordonCuneta, "ch": LocalidadCordobaHogar, "ml": ProyectoML}[programa]
    entidad = await db_session.get(modelo, entidades[programa])
    entidad.ejuridico, entidad.estado_general = FINANCIERO, 999
    await db_session.flush()

    url = f"{ENTIDAD[programa]}/{entidades[programa]}"
    r = await client.patch(url, json={"ejuridico": FINANCIERO, "estado_general": 999, "obs": "sigue editable"})
    assert r.status_code == 200, r.text

    r = await client.patch(url, json={"ejuridico": FINANCIERO, "efinanciero": GENERAL})
    assert r.status_code == 422
    assert "efinanciero" in r.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_alta_de_entidad_valida_el_listado(client: AsyncClient, entidades: dict[str, str]):
    r = await client.post(BASES["cc"], json={
        "municipio": "Otro Pueblo", "departamento": "Depto", "ejuridico": FINANCIERO,
    })
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ESTADO_DE_OTRO_LISTADO"


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", list(BASES))
async def test_operador_crea_y_edita_estados_pero_no_borra(client_operador: AsyncClient, programa: str):
    base = BASES[programa]
    r = await client_operador.post(f"{base}/estados", json={**NUEVO, "dimension": "juridico"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert (await client_operador.patch(f"{base}/estados/{eid}", json={"label": "Corregido"})).status_code == 200
    assert (await client_operador.delete(f"{base}/estados/{eid}")).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("programa", list(BASES))
async def test_consulta_no_administra_estados(client_consulta: AsyncClient, programa: str):
    r = await client_consulta.post(f"{BASES[programa]}/estados", json={**NUEVO, "dimension": "juridico"})
    assert r.status_code == 403
