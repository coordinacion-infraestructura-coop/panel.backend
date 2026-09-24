"""app.integrations.privada_sync — vinculación Vivienda -> Privada (ADR-020).

Unit tests sobre `sync_gestion_privada` en aislamiento (sin pasar por
crear_municipio/etc.) — mockea `httpx.AsyncClient` y `_mint_id_token`, nunca toca
la red. `settings.privada_sync_gestiones_enabled` está en `False` por defecto: el
fixture `_privada_sync_on` lo prende sólo para los tests que lo necesitan.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.integrations.models import VinculoPrivada, VinculoPrivadaSyncLog
from app.integrations.privada_sync import sync_gestion_privada
from app.notificaciones.models import Notificacion


@pytest.fixture(autouse=True)
def _sin_audit_log_real():
    # log_audit hace CAST(:payload AS jsonb) — específico de PostgreSQL. Estos tests
    # llaman a sync_gestion_privada directo (sin pasar por el `client` HTTP, que ya
    # parchea esto vía _AUDIT_PATCH_TARGETS en conftest), así que se parchea acá.
    with patch("app.notificaciones.service.log_audit", new=AsyncMock()):
        yield


@pytest_asyncio.fixture
async def _privada_sync_on():
    prev_enabled = settings.privada_sync_gestiones_enabled
    prev_url = settings.svc_privada_internal_url
    settings.privada_sync_gestiones_enabled = True
    settings.svc_privada_internal_url = "https://svc-privada.example"
    yield
    settings.privada_sync_gestiones_enabled = prev_enabled
    settings.svc_privada_internal_url = prev_url


def _mock_response(status_code: int, body: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = str(body)
    return resp


class _FakeAsyncClient:
    """Reemplaza a `httpx.AsyncClient` en estos tests — nunca pega a la red."""

    def __init__(self, response=None, side_effect=None):
        self._response = response
        self._side_effect = side_effect

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        if self._side_effect is not None:
            raise self._side_effect
        return self._response


def _patched_client(response=None, side_effect=None):
    """Parchea `httpx.AsyncClient` en el módulo bajo test para que `.post(...)`
    devuelva `response` (o lance `side_effect`), sin pegarle a la red ni a Google.
    Devuelve el patcher de la CLASE (útil para `assert_not_called()`) y el de
    `_mint_id_token`."""
    factory = MagicMock(side_effect=lambda *a, **kw: _FakeAsyncClient(response=response, side_effect=side_effect))
    return patch("app.integrations.privada_sync.httpx.AsyncClient", factory), \
        patch("app.integrations.privada_sync._mint_id_token", return_value=None)


async def _call(db_session, **overrides):
    kwargs = dict(
        caso_tipo="cc", caso_id="caso-1", nro_expediente="EXP-1",
        localidad="AMBOY", departamento="CALAMUCHITA", ok_gob="SI",
    )
    kwargs.update(overrides)
    await sync_gestion_privada(db_session, **kwargs)


@pytest.mark.asyncio
async def test_flag_apagado_no_llama(db_session):
    p_client, p_token = _patched_client(response=_mock_response(200, {}))
    with p_client as m_client, p_token:
        await _call(db_session)
        m_client.assert_not_called()

    total_vinculos = (await db_session.execute(select(func.count()).select_from(VinculoPrivada))).scalar_one()
    total_logs = (await db_session.execute(select(func.count()).select_from(VinculoPrivadaSyncLog))).scalar_one()
    assert total_vinculos == 0 and total_logs == 0


@pytest.mark.asyncio
async def test_linked_new_crea_vinculo(db_session, _privada_sync_on):
    body = {"resultado": "LINKED_NEW", "id_legacy": "vivienda:cc:caso-1", "gestion_id": "g-1"}
    p_client, p_token = _patched_client(response=_mock_response(200, body))
    with p_client, p_token:
        await _call(db_session)

    vinculo = (await db_session.execute(select(VinculoPrivada))).scalar_one()
    assert vinculo.caso_tipo == "cc" and vinculo.caso_id == "caso-1"
    assert vinculo.estado_vinculo == "LINKED"
    assert vinculo.gestion_id == "g-1"
    assert vinculo.ultimo_ok_at is not None

    log = (await db_session.execute(select(VinculoPrivadaSyncLog))).scalar_one()
    assert log.resultado == "LINKED_NEW" and log.http_status == 200

    notif = (await db_session.execute(select(Notificacion))).scalar_one()
    assert notif.destino_tipo == "secretaria" and notif.destino_valor == "privada"
    assert notif.nivel == "info" and notif.origen == "privada_sync"
    assert "Nueva gestión" in notif.titulo
    assert "AMBOY" in notif.mensaje and "CALAMUCHITA" in notif.mensaje


@pytest.mark.asyncio
async def test_linked_existing_con_diff_genera_notificacion(db_session, _privada_sync_on):
    diff = {"categoria_id": {"antes": None, "despues": 1756700000003}}
    body = {"resultado": "LINKED_EXISTING", "id_legacy": "vivienda:cc:caso-1", "gestion_id": "g-2", "diff": diff}
    p_client, p_token = _patched_client(response=_mock_response(200, body))
    with p_client, p_token:
        await _call(db_session)

    vinculo = (await db_session.execute(select(VinculoPrivada))).scalar_one()
    assert vinculo.estado_vinculo == "LINKED" and vinculo.gestion_id == "g-2"

    notif = (await db_session.execute(select(Notificacion))).scalar_one()
    assert notif.destino_tipo == "secretaria" and notif.destino_valor == "privada"
    assert notif.nivel == "info" and notif.origen == "privada_sync"
    assert "categoria_id" in notif.mensaje
    assert "AMBOY" in notif.mensaje and "CALAMUCHITA" in notif.mensaje


@pytest.mark.asyncio
async def test_linked_existing_sin_diff_no_notifica(db_session, _privada_sync_on):
    body = {"resultado": "LINKED_EXISTING", "id_legacy": "vivienda:cc:caso-1", "gestion_id": "g-3", "diff": None}
    p_client, p_token = _patched_client(response=_mock_response(200, body))
    with p_client, p_token:
        await _call(db_session)

    total_notif = (await db_session.execute(select(func.count()).select_from(Notificacion))).scalar_one()
    assert total_notif == 0


@pytest.mark.asyncio
async def test_pending_review_notifica_y_no_marca_linked(db_session, _privada_sync_on):
    body = {
        "resultado": "PENDING_REVIEW", "id_legacy": "vivienda:cc:caso-1",
        "motivo": "LOCALIDAD_DEPARTAMENTO_AMBIGUO", "candidatos": ["g-a", "g-b"],
    }
    p_client, p_token = _patched_client(response=_mock_response(200, body))
    with p_client, p_token:
        await _call(db_session, nro_expediente=None)

    vinculo = (await db_session.execute(select(VinculoPrivada))).scalar_one()
    assert vinculo.estado_vinculo == "PENDING_REVIEW"
    assert vinculo.gestion_id is None

    notif = (await db_session.execute(select(Notificacion))).scalar_one()
    assert notif.nivel == "advertencia"
    assert "revisión manual" in notif.mensaje
    assert "AMBOY" in notif.mensaje and "CALAMUCHITA" in notif.mensaje


@pytest.mark.asyncio
async def test_timeout_no_rompe_y_no_notifica(db_session, _privada_sync_on):
    p_client, p_token = _patched_client(side_effect=TimeoutError("timeout"))
    with p_client, p_token:
        await _call(db_session)  # no debe lanzar

    vinculo = (await db_session.execute(select(VinculoPrivada))).scalar_one()
    assert vinculo.estado_vinculo == "ERROR"

    log = (await db_session.execute(select(VinculoPrivadaSyncLog))).scalar_one()
    assert log.resultado == "ERROR" and "timeout" in log.error_detalle

    total_notif = (await db_session.execute(select(func.count()).select_from(Notificacion))).scalar_one()
    assert total_notif == 0


@pytest.mark.asyncio
async def test_error_no_degrada_vinculo_ya_linked(db_session, _privada_sync_on):
    ok_body = {"resultado": "LINKED_NEW", "id_legacy": "vivienda:cc:caso-1", "gestion_id": "g-9"}
    p_client, p_token = _patched_client(response=_mock_response(200, ok_body))
    with p_client, p_token:
        await _call(db_session)

    p_client2, p_token2 = _patched_client(side_effect=RuntimeError("caído"))
    with p_client2, p_token2:
        await _call(db_session)

    vinculo = (await db_session.execute(select(VinculoPrivada))).scalar_one()
    assert vinculo.estado_vinculo == "LINKED"  # no se degrada por el fallo transitorio
    assert vinculo.gestion_id == "g-9"

    total_logs = (await db_session.execute(select(func.count()).select_from(VinculoPrivadaSyncLog))).scalar_one()
    assert total_logs == 2  # ambos intentos quedan trazados


@pytest.mark.asyncio
async def test_crear_municipio_end_to_end_dispara_sync(client, _privada_sync_on):
    """Prueba de cableado real: POST /cordon-cuneta -> crear_municipio -> el hook
    llama a sync_gestion_privada con los datos correctos de la entidad recién creada."""
    body = {"resultado": "LINKED_NEW", "id_legacy": "x", "gestion_id": "g-cc"}
    p_client, p_token = _patched_client(response=_mock_response(200, body))
    with p_client as m_client, p_token:
        r = await client.post(
            "/api/v1/vivienda/cordon-cuneta",
            json={"municipio": "Villa Nueva", "departamento": "Colón", "expediente": "EXP-CC-1"},
        )
        assert r.status_code == 201
        m_client.assert_called_once()

    caso_id = r.json()["id"]
    vinculo = (await client.get("/api/v1/vivienda/cordon-cuneta")).json()  # sanity: el caso quedó creado
    assert any(m["id"] == caso_id for m in vinculo["municipios"])
