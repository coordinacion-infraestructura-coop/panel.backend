"""Checklist Técnico v1.6.0 — avance de obra, fecha de fin, hitos en paneles y "No Aplica".

spec-checklist-tecnico-dgv.md v1.6.0 §5.4-bis, §5.5, §5.6, §6-bis.
"""
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist_tecnico.models import CatalogoItemEstado
from app.cordon_cuneta.models import MunicipioCordonCuneta
from tests.conftest import test_engine
from tests.test_checklist_tecnico import (  # noqa: F401 — fixtures compartidos
    BASE,
    CC_BASE,
    CH_BASE,
    ITEM_ESTADO_COMPLETO,
    ITEM_ESTADO_INICIAL,
    ML_BASE,
    catalogos,
    localidad_ch,
    municipio_cc,
    proyecto_ml,
)

ITEM_ESTADO_NO_APLICA = 6
HOY = date.today()


def _dia(dias_atras: int) -> str:
    return str(HOY - timedelta(days=dias_atras))


@pytest_asyncio.fixture
async def no_aplica(db_session: AsyncSession, catalogos: None) -> None:
    """La fila que siembra la migración 0039 (orden máximo, excluye_completitud)."""
    db_session.add(CatalogoItemEstado(
        id=ITEM_ESTADO_NO_APLICA, label="No Proyectado / No Aplica", orden=5, activo=True,
        bg="#e2e8f0", text_color="#475569", es_completo=False, excluye_completitud=True,
    ))
    await db_session.flush()


async def _medir(client: AsyncClient, prog: str, eid: str, fecha: str, pct: int):
    return await client.post(f"{BASE}/{prog}/{eid}/avance", json={"fecha_medicion": fecha, "porcentaje": pct})


# ── Historial de avance ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_avance_sin_mediciones_es_null_no_cero(client: AsyncClient, municipio_cc: str, catalogos: None):
    data = (await client.get(f"{BASE}/cc/{municipio_cc}")).json()
    assert data["avance"] is None
    assert data["fecha_fin_obra"] is None
    assert all(h["fecha_medicion"] is None for h in data["hitos"])
    assert (await client.get(f"{BASE}/cc/{municipio_cc}/avance")).json() == []


@pytest.mark.asyncio
async def test_avance_vigente_es_la_medicion_mas_reciente_por_fecha(
    client: AsyncClient, municipio_cc: str, catalogos: None
):
    for dias, pct in [(30, 15), (2, 55), (15, 40)]:  # cargadas fuera de orden
        r = await _medir(client, "cc", municipio_cc, _dia(dias), pct)
        assert r.status_code == 201
        assert r.json()["created_by"]

    lista = (await client.get(f"{BASE}/cc/{municipio_cc}/avance")).json()
    assert [m["porcentaje"] for m in lista] == [55, 40, 15]  # más nueva primero

    data = (await client.get(f"{BASE}/cc/{municipio_cc}")).json()
    assert data["avance"] == {"porcentaje": 55, "fecha_medicion": _dia(2)}


@pytest.mark.asyncio
async def test_avance_menor_al_anterior_se_acepta(client: AsyncClient, municipio_cc: str, catalogos: None):
    await _medir(client, "cc", municipio_cc, _dia(5), 60)
    assert (await _medir(client, "cc", municipio_cc, _dia(0), 50)).status_code == 201
    assert (await client.get(f"{BASE}/cc/{municipio_cc}")).json()["avance"]["porcentaje"] == 50


@pytest.mark.asyncio
@pytest.mark.parametrize("pct", [-1, 101])
async def test_avance_porcentaje_fuera_de_rango_422(
    client: AsyncClient, municipio_cc: str, catalogos: None, pct: int
):
    assert (await _medir(client, "cc", municipio_cc, _dia(0), pct)).status_code == 422


@pytest.mark.asyncio
async def test_avance_fecha_futura_422(client: AsyncClient, municipio_cc: str, catalogos: None):
    assert (await _medir(client, "cc", municipio_cc, _dia(-1), 10)).status_code == 422


@pytest.mark.asyncio
async def test_avance_entidad_inexistente_404(client: AsyncClient, catalogos: None):
    assert (await _medir(client, "cc", str(uuid.uuid4()), _dia(0), 10)).status_code == 404


@pytest.mark.asyncio
async def test_eliminar_avance_vuelve_a_la_medicion_anterior(
    client: AsyncClient, municipio_cc: str, catalogos: None
):
    await _medir(client, "cc", municipio_cc, _dia(5), 30)
    nueva = (await _medir(client, "cc", municipio_cc, _dia(0), 80)).json()

    assert (await client.delete(f"{BASE}/cc/{municipio_cc}/avance/{nueva['id']}")).status_code == 204
    assert (await client.get(f"{BASE}/cc/{municipio_cc}")).json()["avance"]["porcentaje"] == 30
    assert len((await client.get(f"{BASE}/cc/{municipio_cc}/avance")).json()) == 1
    # Borrar dos veces → 404 (ya no está vigente)
    assert (await client.delete(f"{BASE}/cc/{municipio_cc}/avance/{nueva['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_eliminar_avance_de_otra_entidad_404(
    client: AsyncClient, municipio_cc: str, localidad_ch: str, catalogos: None
):
    m = (await _medir(client, "cc", municipio_cc, _dia(0), 30)).json()
    assert (await client.delete(f"{BASE}/ch/{localidad_ch}/avance/{m['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_fecha_medicion_de_hitos_derivada_del_historial(
    client: AsyncClient, municipio_cc: str, catalogos: None
):
    for dias, pct in [(40, 45), (20, 72), (5, 75)]:
        await _medir(client, "cc", municipio_cc, _dia(dias), pct)
    # el pago es independiente de la medición
    await client.patch(f"{BASE}/cc/{municipio_cc}/hitos/40", json={"fecha_acreditado": _dia(0)})

    hitos = {h["tipo"]: h for h in (await client.get(f"{BASE}/cc/{municipio_cc}")).json()["hitos"]}
    assert hitos["anticipo"]["fecha_medicion"] is None
    assert hitos["40"]["fecha_medicion"] == _dia(40)  # primera medición >= 40
    assert hitos["40"]["fecha_acreditado"] == _dia(0)
    assert hitos["70"]["fecha_medicion"] == _dia(20)
    assert hitos["70"]["fecha_acreditado"] is None
    assert hitos["100"]["fecha_medicion"] is None


@pytest.mark.asyncio
async def test_fecha_fin_obra_se_carga_y_vacia_sin_tocar_estado(
    client: AsyncClient, municipio_cc: str, catalogos: None
):
    r = await client.patch(f"{BASE}/cc/{municipio_cc}", json={"fecha_fin_obra": _dia(0)})
    assert r.status_code == 200
    assert r.json()["fecha_fin_obra"] == _dia(0)
    assert r.json()["estado_expediente_id"] is None  # no cambia el Estado del expediente
    r = await client.patch(f"{BASE}/cc/{municipio_cc}", json={"fecha_fin_obra": None})
    assert r.json()["fecha_fin_obra"] is None


# Un solo cliente por test: los fixtures de cliente comparten el override global de la app.

@pytest.mark.asyncio
async def test_avance_tecnico_dgv_carga_y_borra(client_tecnico_dgv: AsyncClient, municipio_cc: str, catalogos: None):
    r = await _medir(client_tecnico_dgv, "cc", municipio_cc, _dia(0), 20)
    assert r.status_code == 201
    assert (await client_tecnico_dgv.delete(f"{BASE}/cc/{municipio_cc}/avance/{r.json()['id']}")).status_code == 204


@pytest.mark.asyncio
async def test_avance_consulta_lee_pero_no_escribe(client_consulta: AsyncClient, municipio_cc: str, catalogos: None):
    assert (await client_consulta.get(f"{BASE}/cc/{municipio_cc}/avance")).status_code == 200
    assert (await _medir(client_consulta, "cc", municipio_cc, _dia(0), 20)).status_code == 403
    assert (await client_consulta.delete(f"{BASE}/cc/{municipio_cc}/avance/{uuid.uuid4()}")).status_code == 403


@pytest.mark.asyncio
async def test_avance_autoridad_no_escribe(client_autoridad: AsyncClient, municipio_cc: str, catalogos: None):
    assert (await _medir(client_autoridad, "cc", municipio_cc, _dia(0), 20)).status_code == 403


# ── Avance + hitos en los paneles (§6-bis) ────────────────────────────────────

@pytest.mark.asyncio
async def test_paneles_exponen_avance_e_hitos_coherentes_con_el_checklist(
    client: AsyncClient, municipio_cc: str, localidad_ch: str, proyecto_ml: str, catalogos: None
):
    entidades = [("cc", municipio_cc), ("ch", localidad_ch), ("ml", proyecto_ml)]
    for prog, eid in entidades:
        await _medir(client, prog, eid, _dia(0), 42)
        await client.patch(f"{BASE}/{prog}/{eid}/hitos/anticipo", json={"fecha_acreditado": _dia(0)})
        await client.patch(f"{BASE}/{prog}/{eid}", json={"fecha_fin_obra": _dia(0)})

    filas = {
        "cc": next(m for m in (await client.get(CC_BASE)).json()["municipios"] if m["id"] == municipio_cc),
        "ch": next(x for x in (await client.get(CH_BASE)).json()["localidades"] if x["id"] == localidad_ch),
        "ml": next(p for p in (await client.get(ML_BASE)).json() if p["id"] == proyecto_ml),
    }
    for prog, eid in entidades:
        fila = filas[prog]
        assert fila["avance_obra_pct"] == 42
        assert fila["avance_obra_fecha"] == _dia(0)
        assert fila["fecha_fin_obra"] == _dia(0)
        chk = (await client.get(f"{BASE}/{prog}/{eid}")).json()
        esperado = [
            {k: h[k] for k in ("tipo", "monto", "fecha_medicion", "fecha_acreditado")} for h in chk["hitos"]
        ]
        assert fila["hitos_obra"] == esperado
        assert [h["tipo"] for h in fila["hitos_obra"]] == ["anticipo", "40", "70", "100"]
        assert fila["hitos_obra"][0]["fecha_acreditado"] == _dia(0)
        assert fila["hitos_obra"][1]["fecha_medicion"] == _dia(0)


@pytest.mark.asyncio
async def test_panel_sin_checklist_devuelve_hitos_null(client: AsyncClient, municipio_cc: str, catalogos: None):
    cc = next(m for m in (await client.get(CC_BASE)).json()["municipios"] if m["id"] == municipio_cc)
    assert cc["avance_obra_pct"] is None
    assert cc["hitos_obra"] is None


@pytest.mark.asyncio
async def test_panel_detalle_ml_expone_avance(client: AsyncClient, proyecto_ml: str, catalogos: None):
    await _medir(client, "ml", proyecto_ml, _dia(0), 70)
    r = await client.get(f"{ML_BASE}/{proyecto_ml}")
    assert r.status_code == 200
    assert r.json()["avance_obra_pct"] == 70
    assert r.json()["hitos_obra"][2]["fecha_medicion"] == _dia(0)


@pytest.mark.asyncio
async def test_panel_update_no_escribe_avance(client: AsyncClient, municipio_cc: str, catalogos: None):
    await client.put(f"{CC_BASE}/{municipio_cc}", json={"avance_obra_pct": 99, "fecha_fin_obra": _dia(0)})
    chk = (await client.get(f"{BASE}/cc/{municipio_cc}")).json()
    assert chk["avance"] is None
    assert chk["fecha_fin_obra"] is None


@pytest.mark.asyncio
async def test_listado_panel_sin_n_mas_1(client: AsyncClient, db_session: AsyncSession, catalogos: None):
    async def _crear(n: int) -> None:
        for i in range(n):
            mid = str(uuid.uuid4())
            db_session.add(MunicipioCordonCuneta(id=mid, orden=i, municipio=f"M-{mid[:8]}", monto=1000))
            await db_session.flush()
            await _medir(client, "cc", mid, _dia(0), 10)

    async def _contar() -> int:
        n = 0

        def _cb(*_args, **_kw):
            nonlocal n
            n += 1

        event.listen(test_engine.sync_engine, "before_cursor_execute", _cb)
        try:
            assert (await client.get(CC_BASE)).status_code == 200
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", _cb)
        return n

    await _crear(1)
    con_uno = await _contar()
    await _crear(4)
    assert await _contar() == con_uno


# ── "No Proyectado / No Aplica" ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_aplica_no_es_estado_por_defecto(client: AsyncClient, municipio_cc: str, no_aplica: None):
    items = (await client.get(f"{BASE}/cc/{municipio_cc}")).json()["items"]
    assert {i["item_estado_id"] for i in items} == {ITEM_ESTADO_INICIAL}
    cat = (await client.get(f"{BASE}/catalogos")).json()["items_estado"]
    na = next(e for e in cat if e["id"] == ITEM_ESTADO_NO_APLICA)
    assert na["excluye_completitud"] is True and na["es_completo"] is False


@pytest.mark.asyncio
async def test_no_aplica_se_descarta_en_resumen_territorial(
    client: AsyncClient, localidad_ch: str, no_aplica: None
):
    # CH: 14 ítems. 2 en No Aplica, 1 completo → total 12, faltan 11.
    for item, estado in [(1, ITEM_ESTADO_NO_APLICA), (2, ITEM_ESTADO_NO_APLICA), (3, ITEM_ESTADO_COMPLETO)]:
        r = await client.patch(f"{BASE}/ch/{localidad_ch}/items/{item}", json={"item_estado_id": estado})
        assert r.status_code == 200

    r = await client.post("/api/v1/resumen-territorial/actualizar")
    assert r.status_code == 200
    lineas = [
        p for loc in r.json()["payload"]["localidades"] for p in loc["programas"]
        if p.get("entidad_id") == localidad_ch
    ]
    assert lineas, r.json()
    assert lineas[0]["checklist_total"] == 12
    assert lineas[0]["checklist_faltan"] == 11


@pytest.mark.asyncio
async def test_admin_item_estado_flags_excluyentes_422(client: AsyncClient, no_aplica: None):
    r = await client.post(f"{BASE}/admin/item-estado", json={
        "label": "X", "orden": 9, "es_completo": True, "excluye_completitud": True,
    })
    assert r.status_code == 422
    r = await client.patch(f"{BASE}/admin/item-estado/{ITEM_ESTADO_NO_APLICA}", json={"es_completo": True})
    assert r.status_code == 422
    r = await client.patch(f"{BASE}/admin/item-estado/{ITEM_ESTADO_COMPLETO}", json={"excluye_completitud": True})
    assert r.status_code == 422
    r = await client.patch(
        f"{BASE}/admin/item-estado/{ITEM_ESTADO_NO_APLICA}", json={"es_completo": True, "excluye_completitud": False}
    )
    assert r.status_code == 200
