"""Asignación manual de localidades sin resolver
(docs/files/spec-geo-asignacion-manual-localidades.md): registro de pendientes
en el resolver, alias por departamento, y los endpoints Admin de
`/api/v1/geo/**` (resolver, descartar, deshacer)."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import LocalidadCordobaHogar
from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.geo import service as geo_service
from app.geo.models import GeoAliasManual, GeoLocalidad, GeoPendiente
from app.notificaciones.models import Notificacion

PENDIENTES_URL = "/api/v1/geo/pendientes"


@pytest.fixture(autouse=True)
def _sin_llamadas_externas():
    """Las llamadas best-effort a svc-privada y el recálculo del Resumen
    Territorial se simulan: acá se prueba el vínculo, no esos flujos."""
    with patch("app.geo.asignacion._normalizar_privada", new=AsyncMock(return_value="aplicado")) as privada, \
         patch("app.geo.asignacion._recalcular_resumen", new=AsyncMock(return_value="aplicado")):
        yield privada


@pytest_asyncio.fixture
async def padron(db_session: AsyncSession) -> None:
    db_session.add_all([
        GeoLocalidad(id_geo="10", departamento="Colón", localidad="VILLA NUEVA ESPERANZA", activo=True),
        GeoLocalidad(id_geo="20", departamento="Unión", localidad="SAN PEDRO", activo=True),
        GeoLocalidad(id_geo="21", departamento="San Alberto", localidad="SAN PEDRO", activo=True),
        GeoLocalidad(id_geo="99", departamento="Colón", localidad="DADA DE BAJA", activo=False),
    ])
    await db_session.flush()


async def _pendientes(db: AsyncSession) -> list[GeoPendiente]:
    return list((await db.execute(select(GeoPendiente))).scalars().all())


# ── resolver_lote: pendientes y notificación ─────────────────────────────────

@pytest.mark.asyncio
async def test_sin_match_registra_pendiente_y_notifica_una_sola_vez(db_session: AsyncSession, padron):
    lote = [("Colón", "Va. Nva. Esperanza"), ("Colón", "Va. Nva. Esperanza"), ("Colón", "Villa Nueva Esperanza")]
    await geo_service.resolver_lote(db_session, lote, origen="gas_pit")
    await geo_service.resolver_lote(db_session, lote, origen="gas_pit")

    pendientes = await _pendientes(db_session)
    assert len(pendientes) == 1
    p = pendientes[0]
    assert (p.origen, p.localidad_original, p.departamento_original) == ("gas_pit", "Va. Nva. Esperanza", "Colón")
    assert p.cantidad == 2  # apariciones del par en el lote
    assert p.estado == "pendiente"

    notifs = (await db_session.execute(select(Notificacion))).scalars().all()
    assert len(notifs) == 1
    assert notifs[0].enlace == "/admin/localidades-sin-resolver"


@pytest.mark.asyncio
async def test_misma_localidad_en_otra_fuente_es_otro_pendiente(db_session: AsyncSession, padron):
    await geo_service.resolver_lote(db_session, [("Colón", "Inexistente")], origen="gas_pit")
    await geo_service.resolver_lote(db_session, [("Colón", "Inexistente")], origen="atp")
    assert {p.origen for p in await _pendientes(db_session)} == {"gas_pit", "atp"}


@pytest.mark.asyncio
async def test_cantidad_informada_por_el_cliente(db_session: AsyncSession, padron):
    await geo_service.resolver_lote(
        db_session, [("Tulumba", "Paraje X")], origen="privada", cantidades=[7],
    )
    assert (await _pendientes(db_session))[0].cantidad == 7


@pytest.mark.asyncio
async def test_pendiente_descartado_que_reaparece_se_reabre_y_notifica(db_session: AsyncSession, padron):
    await geo_service.resolver_lote(db_session, [("Colón", "Inexistente")], origen="atp")
    p = (await _pendientes(db_session))[0]
    p.estado = "descartada"
    await db_session.flush()

    await geo_service.resolver_lote(db_session, [("Colón", "Inexistente")], origen="atp")
    assert (await _pendientes(db_session))[0].estado == "pendiente"
    assert len((await db_session.execute(select(Notificacion))).scalars().all()) == 2


# ── alias por texto + departamento ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_alias_por_departamento_no_captura_al_homonimo(db_session: AsyncSession, padron):
    db_session.add(GeoAliasManual(
        texto_normalizado="santa teresa", departamento_normalizado="capital",
        texto_original="Santa Teresa", id_geo=None, motivo="barrio de Capital",
    ))
    db_session.add(GeoLocalidad(id_geo="30", departamento="Río Cuarto", localidad="SANTA TERESA", activo=True))
    await db_session.flush()

    barrio = await geo_service.resolver_uno(db_session, "Capital", "Santa Teresa")
    assert (barrio.match_tipo, barrio.id_geo) == ("manual", None)
    localidad = await geo_service.resolver_uno(db_session, "Río Cuarto", "Santa Teresa")
    assert (localidad.match_tipo, localidad.id_geo) == ("exacto", "30")


@pytest.mark.asyncio
async def test_alias_por_departamento_gana_sobre_el_global(db_session: AsyncSession, padron):
    db_session.add_all([
        GeoAliasManual(texto_normalizado="s. pedro", departamento_normalizado="", texto_original="S. Pedro", id_geo="20"),
        GeoAliasManual(texto_normalizado="s. pedro", departamento_normalizado="san alberto", texto_original="S. Pedro", id_geo="21"),
    ])
    await db_session.flush()
    assert (await geo_service.resolver_uno(db_session, "San Alberto", "S. Pedro")).id_geo == "21"
    assert (await geo_service.resolver_uno(db_session, "Unión", "S. Pedro")).id_geo == "20"


@pytest.mark.asyncio
async def test_alias_dado_de_baja_no_se_usa(db_session: AsyncSession, padron):
    from datetime import datetime, timezone
    db_session.add(GeoAliasManual(
        texto_normalizado="s. pedro", texto_original="S. Pedro", id_geo="20",
        deleted_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()
    assert (await geo_service.resolver_uno(db_session, "Unión", "S. Pedro")).match_tipo == "sin_match"


# ── endpoints Admin ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def pendiente_cc(db_session: AsyncSession, padron) -> dict:
    """Un municipio de Cordón Cuneta cargado con una grafía que no resuelve, y
    su pendiente (como lo deja `resolver_uno` al guardar el registro)."""
    cc = MunicipioCordonCuneta(
        id=str(uuid.uuid4()), orden=1, municipio="Va. Nva. Esperanza", departamento="Colon",
    )
    db_session.add(cc)
    await geo_service.resolver_uno(db_session, cc.departamento, cc.municipio, origen="cordon_cuneta")
    await db_session.flush()
    return {"cc": cc, "pendiente": (await _pendientes(db_session))[0]}


@pytest.mark.asyncio
async def test_listar_pendientes_cuenta_registros_de_vivienda_en_vivo(client: AsyncClient, pendiente_cc):
    r = await client.get(PENDIENTES_URL)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert (item["origen"], item["localidad"], item["departamento"]) == ("cordon_cuneta", "Va. Nva. Esperanza", "Colon")
    assert item["cantidad"] == 1
    assert item["alias"] is None


@pytest.mark.asyncio
async def test_resolver_dry_run_muestra_impacto_y_no_escribe(client: AsyncClient, db_session, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    r = await client.post(
        f"{PENDIENTES_URL}/{pid}/resolver",
        json={"id_geo": "10", "motivo": "abreviatura", "dry_run": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["registros"] == [{
        "programa": "cordon_cuneta", "id": pendiente_cc["cc"].id,
        "nombre_actual": "Va. Nva. Esperanza", "departamento_actual": "Colon",
        "nombre_oficial": "VILLA NUEVA ESPERANZA", "departamento_oficial": "Colón",
    }]
    assert (await db_session.execute(select(GeoAliasManual))).scalars().all() == []
    assert pendiente_cc["cc"].localidad_id is None


@pytest.mark.asyncio
async def test_resolver_vincula_y_propaga_nombre_oficial(
    client: AsyncClient, db_session, pendiente_cc, _sin_llamadas_externas
):
    pid = pendiente_cc["pendiente"].id
    r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "motivo": "abreviatura"})
    assert r.status_code == 200
    body = r.json()
    assert body["pendientes_resueltos"] == 1
    assert body["propagacion"]["gasifera"] == "proximo_sync"
    assert body["propagacion"]["privada"] == "aplicado"
    _sin_llamadas_externas.assert_awaited_once()

    cc = pendiente_cc["cc"]
    assert (cc.localidad_id, cc.localidad_match_tipo) == ("10", "manual")
    assert (cc.municipio, cc.departamento) == ("VILLA NUEVA ESPERANZA", "Colón")

    alias = (await db_session.execute(select(GeoAliasManual))).scalar_one()
    assert (alias.texto_normalizado, alias.departamento_normalizado, alias.id_geo) == (
        "va. nva. esperanza", "colon", "10",
    )
    assert alias.created_by == "admin@test.com"
    assert pendiente_cc["pendiente"].estado == "resuelta"

    # El resolver ya lo devuelve vinculado y no vuelve a quedar pendiente.
    resuelto = await geo_service.resolver_uno(db_session, "Colón", "Va. Nva. Esperanza", origen="gas_pit")
    assert (resuelto.id_geo, resuelto.match_tipo) == ("10", "manual")
    assert (await client.get(PENDIENTES_URL)).json()["total"] == 0


@pytest.mark.asyncio
async def test_resolver_cierra_el_mismo_pendiente_de_otras_fuentes(client: AsyncClient, db_session, pendiente_cc):
    await geo_service.resolver_lote(db_session, [("Colón", "Va. Nva. Esperanza")], origen="atp")
    await geo_service.resolver_lote(db_session, [("Unión", "Va. Nva. Esperanza")], origen="atp")
    pid = pendiente_cc["pendiente"].id

    r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "motivo": "abreviatura"})
    assert r.json()["pendientes_resueltos"] == 2  # cordon_cuneta + atp de Colón; el de Unión sigue abierto
    abiertos = (await client.get(PENDIENTES_URL)).json()["items"]
    assert [(p["origen"], p["departamento"]) for p in abiertos] == [("atp", "Unión")]


@pytest.mark.asyncio
async def test_resolver_avisa_si_queda_un_duplicado_y_vincula_igual(client: AsyncClient, db_session, pendiente_cc):
    db_session.add(MunicipioCordonCuneta(
        id=str(uuid.uuid4()), orden=2, municipio="VILLA NUEVA ESPERANZA", departamento="Colón", localidad_id="10",
    ))
    await db_session.flush()
    pid = pendiente_cc["pendiente"].id
    r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "motivo": "abreviatura"})
    assert r.status_code == 200
    assert r.json()["duplicados"] == [{"programa": "cordon_cuneta", "cantidad": 2}]
    assert pendiente_cc["cc"].localidad_id == "10"


@pytest.mark.asyncio
async def test_confirmar_sin_vinculo(client: AsyncClient, db_session, pendiente_cc, _sin_llamadas_externas):
    pid = pendiente_cc["pendiente"].id
    r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": None, "motivo": "paraje fuera del padrón"})
    assert r.status_code == 200
    assert r.json()["propagacion"]["privada"] == "no_aplica"
    _sin_llamadas_externas.assert_not_awaited()

    cc = pendiente_cc["cc"]
    assert (cc.localidad_id, cc.localidad_match_tipo, cc.municipio) == (None, "manual", "Va. Nva. Esperanza")
    resuelto = await geo_service.resolver_uno(db_session, "Colón", "Va. Nva. Esperanza", origen="cordon_cuneta")
    assert (resuelto.id_geo, resuelto.match_tipo) == (None, "manual")


@pytest.mark.asyncio
async def test_resolver_alcance_global(client: AsyncClient, db_session, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    await client.post(
        f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "alcance": "global", "motivo": "abreviatura"},
    )
    alias = (await db_session.execute(select(GeoAliasManual))).scalar_one()
    assert alias.departamento_normalizado == ""
    assert (await geo_service.resolver_uno(db_session, "Unión", "Va. Nva. Esperanza")).id_geo == "10"


@pytest.mark.asyncio
async def test_resolver_rechaza_localidad_inactiva_o_inexistente(client: AsyncClient, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    for id_geo in ("99", "no-existe"):
        r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": id_geo, "motivo": "abreviatura"})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "LOCALIDAD_INVALIDA"


@pytest.mark.asyncio
async def test_resolver_exige_motivo(client: AsyncClient, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_resolver_dos_veces_da_409(client: AsyncClient, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    body = {"id_geo": "10", "motivo": "abreviatura"}
    assert (await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json=body)).status_code == 200
    assert (await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_resolver_pendiente_inexistente_404(client: AsyncClient, padron):
    r = await client.post(f"{PENDIENTES_URL}/no-existe/resolver", json={"id_geo": "10", "motivo": "abreviatura"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_descartar_saca_el_pendiente_sin_crear_alias(client: AsyncClient, db_session, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    assert (await client.post(f"{PENDIENTES_URL}/{pid}/descartar")).status_code == 200
    assert (await client.get(PENDIENTES_URL)).json()["total"] == 0
    assert (await client.get(PENDIENTES_URL, params={"estado": "descartada"})).json()["total"] == 1
    assert (await db_session.execute(select(GeoAliasManual))).scalars().all() == []


@pytest.mark.asyncio
async def test_deshacer_restaura_el_registro_y_reabre_el_pendiente(client: AsyncClient, db_session, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "motivo": "abreviatura"})

    r = await client.post(f"{PENDIENTES_URL}/{pid}/deshacer")
    assert r.status_code == 200
    assert r.json()["registros_restaurados"] == 1
    assert r.json()["pendientes_reabiertos"] == 1

    cc = pendiente_cc["cc"]
    assert (cc.municipio, cc.departamento, cc.localidad_id, cc.localidad_match_tipo) == (
        "Va. Nva. Esperanza", "Colon", None, None,
    )
    assert pendiente_cc["pendiente"].estado == "pendiente"
    alias = (await db_session.execute(select(GeoAliasManual))).scalar_one()
    assert alias.deleted_at is not None
    assert (await geo_service.resolver_uno(db_session, "Colon", "Va. Nva. Esperanza")).match_tipo == "sin_match"
    # Con el alias dado de baja se puede volver a vincular (a otra localidad).
    r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "20", "motivo": "corrección"})
    assert r.status_code == 200
    assert cc.localidad_id == "20"


@pytest.mark.asyncio
async def test_deshacer_no_pisa_un_registro_editado_despues(client: AsyncClient, db_session, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "motivo": "abreviatura"})
    cc = pendiente_cc["cc"]
    cc.municipio, cc.localidad_id = "SAN PEDRO", "20"  # alguien lo corrigió a mano
    await db_session.flush()

    r = await client.post(f"{PENDIENTES_URL}/{pid}/deshacer")
    assert (r.json()["registros_restaurados"], r.json()["registros_omitidos"]) == (0, 1)
    assert (cc.municipio, cc.localidad_id) == ("SAN PEDRO", "20")


@pytest.mark.asyncio
async def test_deshacer_sin_vinculo_previo_409(client: AsyncClient, pendiente_cc):
    r = await client.post(f"{PENDIENTES_URL}/{pendiente_cc['pendiente'].id}/deshacer")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_listar_alias(client: AsyncClient, pendiente_cc):
    pid = pendiente_cc["pendiente"].id
    await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "motivo": "abreviatura"})
    body = (await client.get("/api/v1/geo/alias")).json()
    assert body["total"] == 1
    assert body["items"][0]["localidad_oficial"] == "VILLA NUEVA ESPERANZA"
    assert body["items"][0]["motivo"] == "abreviatura"


@pytest.mark.asyncio
async def test_cordoba_hogar_tambien_se_propaga(client: AsyncClient, db_session, pendiente_cc):
    ch = LocalidadCordobaHogar(
        id=str(uuid.uuid4()), orden=1, localidad="VA. NVA. ESPERANZA", departamento="Colón",
    )
    db_session.add(ch)
    await db_session.flush()
    pid = pendiente_cc["pendiente"].id
    r = await client.post(f"{PENDIENTES_URL}/{pid}/resolver", json={"id_geo": "10", "motivo": "abreviatura"})
    assert {reg["programa"] for reg in r.json()["registros"]} == {"cordon_cuneta", "cordoba_hogar"}
    assert (ch.localidad, ch.localidad_id) == ("VILLA NUEVA ESPERANZA", "10")


@pytest.mark.parametrize("metodo,ruta", [
    ("get", PENDIENTES_URL),
    ("get", "/api/v1/geo/alias"),
    ("post", f"{PENDIENTES_URL}/x/resolver"),
    ("post", f"{PENDIENTES_URL}/x/descartar"),
    ("post", f"{PENDIENTES_URL}/x/deshacer"),
])
@pytest.mark.asyncio
async def test_solo_admin(client_operador: AsyncClient, metodo: str, ruta: str):
    r = await getattr(client_operador, metodo)(ruta)
    assert r.status_code == 403
