"""Tests de integración para el módulo checklist_tecnico (panel editable DGV)."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico.models import CatalogoEstadoExpediente, CatalogoReparticion
from app.cordoba_hogar.models import LocalidadCordobaHogar
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.mi_lugar.models import ProyectoML

BASE = "/api/v1/vivienda/checklist-tecnico"
CC_BASE = "/api/v1/vivienda/cordon-cuneta"
CH_BASE = "/api/v1/vivienda/cordoba-hogar"
ML_BASE = "/api/v1/vivienda/mi-lugar/proyectos"
PROGRAMAS_BASE = "/api/v1/vivienda/programas"


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def catalogos(db_session: AsyncSession) -> None:
    """Mismo seed que la migración 0022 (7 estados + 3 reparticiones)."""
    estados = [
        "A INICIAR en DGV", "En CURSO en DGV", "COMPLETO en DGV",
        "En CURSO en TC", "APROBADO por TC", "OBRA en EJECUCIÓN", "OBRA TERMINADA",
    ]
    for i, label in enumerate(estados, start=1):
        db_session.add(CatalogoEstadoExpediente(id=i, label=label, orden=i - 1, activo=True))
    reparticiones = [
        "Dirección de Regularización de Obras y Proyectos",
        "Dirección Legal y Notarial",
        "Área Coordinación Administrativa",
    ]
    for i, label in enumerate(reparticiones, start=1):
        db_session.add(CatalogoReparticion(id=i, programa=None, label=label, orden=i - 1, activo=True))
    await db_session.flush()


@pytest_asyncio.fixture
async def municipio_cc(db_session: AsyncSession) -> str:
    mid = str(uuid.uuid4())
    db_session.add(MunicipioCordonCuneta(
        id=mid, orden=1, municipio="Chazón", departamento="General San Martín",
        expediente="0423-080480/2026", monto=100_000_000,
    ))
    await db_session.flush()
    return mid


@pytest_asyncio.fixture
async def localidad_ch(db_session: AsyncSession) -> str:
    lid = str(uuid.uuid4())
    db_session.add(LocalidadCordobaHogar(
        id=lid, orden=1, localidad="Colonia Barge", departamento="Marcos Juárez",
        expediente="0423-079784/2026", monto=2_720_000_000, cantidad_casas=80,
    ))
    await db_session.flush()
    return lid


@pytest_asyncio.fixture
async def proyecto_ml(db_session: AsyncSession) -> str:
    pid = str(uuid.uuid4())
    db_session.add(ProyectoML(
        id=pid, tipo="exp", nombre="Predio Norte", localidad_nombre="Villa María",
        departamento="General San Martín", expediente="ML-001/2026", monto=50_000_000, lotes=20,
    ))
    await db_session.flush()
    return pid


# ── Catálogos ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_catalogos(client: AsyncClient, catalogos: None):
    r = await client.get(f"{BASE}/catalogos")
    assert r.status_code == 200
    data = r.json()
    assert len(data["estados_expediente"]) == 7
    assert data["estados_expediente"][0]["label"] == "A INICIAR en DGV"
    assert len(data["reparticiones"]) == 3
    assert set(data["items_por_programa"].keys()) == {"cc", "ch", "ml"}
    assert len(data["items_por_programa"]["cc"]) == 9
    assert len(data["items_por_programa"]["ch"]) == 14
    assert len(data["items_por_programa"]["ml"]) == 14
    item4 = next(i for i in data["items_por_programa"]["cc"] if i["item_num"] == 4)
    assert len(item4["sub_items"]) == 10
    item14_ml = next(i for i in data["items_por_programa"]["ml"] if i["item_num"] == 14)
    assert len(item14_ml["sub_items"]) == 6


# ── GET checklist — creación on-the-fly ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_checklist_crea_fila_on_the_fly(client: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client.get(f"{BASE}/cc/{municipio_cc}")
    assert r.status_code == 200
    data = r.json()
    assert data["estado_expediente_id"] is None
    assert data["entidad"]["nombre"] == "Chazón"
    assert data["entidad"]["monto"] == 100_000_000
    # 9 items top-level + 10 sub-items del item 4 = 19
    assert len(data["items"]) == 19
    assert all(i["valor"] == "sin_presentar" for i in data["items"])
    assert data["hitos"] is not None
    assert len(data["hitos"]) == 4


@pytest.mark.asyncio
async def test_get_checklist_es_idempotente(client: AsyncClient, municipio_cc: str, catalogos: None):
    r1 = await client.get(f"{BASE}/cc/{municipio_cc}")
    r2 = await client.get(f"{BASE}/cc/{municipio_cc}")
    assert r1.json()["items"] == r2.json()["items"]


@pytest.mark.asyncio
async def test_get_checklist_entidad_inexistente_404(client: AsyncClient, catalogos: None):
    r = await client.get(f"{BASE}/cc/{uuid.uuid4()}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_checklist_ch_sin_hitos(client: AsyncClient, localidad_ch: str, catalogos: None):
    r = await client.get(f"{BASE}/ch/{localidad_ch}")
    assert r.status_code == 200
    data = r.json()
    assert data["hitos"] is None
    assert len(data["items"]) == 14


@pytest.mark.asyncio
async def test_get_checklist_ml_item14_con_6_subitems(client: AsyncClient, proyecto_ml: str, catalogos: None):
    r = await client.get(f"{BASE}/ml/{proyecto_ml}")
    assert r.status_code == 200
    data = r.json()
    # 14 items top-level (incluye el ítem 14 "padre") + 6 sub-items del ítem 14 = 20
    assert len(data["items"]) == 20
    sub_items_14 = [i for i in data["items"] if i["item_num"] == 14 and i["sub_item_num"] is not None]
    assert len(sub_items_14) == 6


# ── Actualizar ítems ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_item_persiste_valor(client: AsyncClient, municipio_cc: str, catalogos: None):
    await client.get(f"{BASE}/cc/{municipio_cc}")  # crea la fila
    r = await client.patch(f"{BASE}/cc/{municipio_cc}/items/1", json={"valor": "completo"})
    assert r.status_code == 200
    item1 = next(i for i in r.json()["items"] if i["item_num"] == 1 and i["sub_item_num"] is None)
    assert item1["valor"] == "completo"


@pytest.mark.asyncio
async def test_actualizar_subitem_persiste_valor(client: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client.patch(f"{BASE}/cc/{municipio_cc}/items/4", json={"valor": "a_corregir", "sub_item_num": 3})
    assert r.status_code == 200
    sub3 = next(i for i in r.json()["items"] if i["item_num"] == 4 and i["sub_item_num"] == 3)
    assert sub3["valor"] == "a_corregir"
    # El item 4 "padre" (sub_item_num null) no debe verse afectado
    padre = next(i for i in r.json()["items"] if i["item_num"] == 4 and i["sub_item_num"] is None)
    assert padre["valor"] == "sin_presentar"


@pytest.mark.asyncio
async def test_actualizar_item_inexistente_404(client: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client.patch(f"{BASE}/cc/{municipio_cc}/items/999", json={"valor": "completo"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_actualizar_item_valor_invalido_422(client: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client.patch(f"{BASE}/cc/{municipio_cc}/items/1", json={"valor": "no_existe"})
    assert r.status_code == 422


# ── Actualizar estado / repartición / fecha ─────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_estado_expediente(client: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client.patch(f"{BASE}/cc/{municipio_cc}", json={"estado_expediente_id": 2, "reparticion_id": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["estado_expediente_id"] == 2
    assert data["estado_expediente_label"] == "En CURSO en DGV"
    assert data["reparticion_id"] == 1


@pytest.mark.asyncio
async def test_actualizar_estado_expediente_inexistente_404(client: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client.patch(f"{BASE}/cc/{municipio_cc}", json={"estado_expediente_id": 999})
    assert r.status_code == 404


# ── Hitos de obra ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hitos_calculan_sobre_convenio(client: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client.get(f"{BASE}/cc/{municipio_cc}")
    hitos = {h["tipo"]: h for h in r.json()["hitos"]}
    assert hitos["anticipo"]["monto"] == 50_000_000  # 50% de 100_000_000
    assert hitos["40"]["monto"] == 25_000_000
    assert hitos["70"]["monto"] == 25_000_000
    assert hitos["100"]["monto"] == 0


@pytest.mark.asyncio
async def test_hito_recalcula_sobre_monto_vigente_no_congelado(
    client: AsyncClient, db_session: AsyncSession, municipio_cc: str, catalogos: None
):
    """Confirmado por el usuario: un hito ya acreditado refleja el monto ACTUAL del convenio,
    no uno congelado al momento de acreditarlo."""
    r = await client.patch(f"{BASE}/cc/{municipio_cc}/hitos/anticipo", json={"fecha_acreditado": "2026-05-08"})
    assert r.status_code == 200
    assert next(h for h in r.json()["hitos"] if h["tipo"] == "anticipo")["monto"] == 50_000_000

    municipio = await db_session.get(MunicipioCordonCuneta, municipio_cc)
    municipio.monto = 200_000_000
    await db_session.flush()

    r2 = await client.get(f"{BASE}/cc/{municipio_cc}")
    hito = next(h for h in r2.json()["hitos"] if h["tipo"] == "anticipo")
    assert hito["monto"] == 100_000_000  # recalculado sobre el monto nuevo
    assert hito["fecha_acreditado"] == "2026-05-08"  # la fecha ya cargada no se pierde


@pytest.mark.asyncio
async def test_hito_404_para_ch_y_ml(client: AsyncClient, localidad_ch: str, proyecto_ml: str, catalogos: None):
    r_ch = await client.patch(f"{BASE}/ch/{localidad_ch}/hitos/anticipo", json={"fecha_acreditado": "2026-05-08"})
    assert r_ch.status_code == 404
    r_ml = await client.patch(f"{BASE}/ml/{proyecto_ml}/hitos/anticipo", json={"fecha_acreditado": "2026-05-08"})
    assert r_ml.status_code == 404


# ── Permisos — TecnicoDGV ve Tablero + Checklist, NUNCA los paneles completos ──

@pytest.mark.asyncio
async def test_tecnico_dgv_accede_a_checklist_y_tablero(
    client_tecnico_dgv: AsyncClient, municipio_cc: str, catalogos: None
):
    r_checklist = await client_tecnico_dgv.get(f"{BASE}/cc/{municipio_cc}")
    assert r_checklist.status_code == 200
    r_tablero = await client_tecnico_dgv.get(PROGRAMAS_BASE)
    assert r_tablero.status_code == 200


@pytest.mark.asyncio
async def test_tecnico_dgv_bloqueado_en_paneles_completos(
    client_tecnico_dgv: AsyncClient, municipio_cc: str, localidad_ch: str, proyecto_ml: str
):
    assert (await client_tecnico_dgv.get(CC_BASE)).status_code == 403
    assert (await client_tecnico_dgv.get(CH_BASE)).status_code == 403
    assert (await client_tecnico_dgv.get(ML_BASE)).status_code == 403


@pytest.mark.asyncio
async def test_tecnico_dgv_puede_escribir_checklist(client_tecnico_dgv: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client_tecnico_dgv.patch(f"{BASE}/cc/{municipio_cc}/items/1", json={"valor": "completo"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_consulta_no_puede_escribir_checklist(client_consulta: AsyncClient, municipio_cc: str, catalogos: None):
    r = await client_consulta.patch(f"{BASE}/cc/{municipio_cc}/items/1", json={"valor": "completo"})
    assert r.status_code == 403


# ── Admin de catálogos ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_crear_estado_expediente(client: AsyncClient, catalogos: None):
    r = await client.post(f"{BASE}/admin/estado-expediente", json={"label": "Nuevo Estado", "orden": 7})
    assert r.status_code == 201
    assert r.json()["label"] == "Nuevo Estado"


@pytest.mark.asyncio
async def test_admin_estado_expediente_403_para_no_admin(client_tecnico_dgv: AsyncClient, catalogos: None):
    r = await client_tecnico_dgv.post(f"{BASE}/admin/estado-expediente", json={"label": "X", "orden": 7})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_estado_expediente_403_para_operador(client_operador: AsyncClient, catalogos: None):
    r = await client_operador.post(f"{BASE}/admin/estado-expediente", json={"label": "X", "orden": 7})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_crear_reparticion_con_programa(client: AsyncClient, catalogos: None):
    r = await client.post(f"{BASE}/admin/reparticion", json={"label": "Solo CH", "orden": 3, "programa": "ch"})
    assert r.status_code == 201
    assert r.json()["programa"] == "ch"


@pytest.mark.asyncio
async def test_admin_actualizar_reparticion(client: AsyncClient, catalogos: None):
    r = await client.patch(f"{BASE}/admin/reparticion/1", json={"activo": False})
    assert r.status_code == 200
    assert r.json()["activo"] is False
