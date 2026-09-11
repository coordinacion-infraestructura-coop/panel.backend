"""Tests del panel de notificaciones internas (spec-notificaciones.md).

- Alta vía el endpoint interno IAM (`POST /internal/notificaciones`) + feed HTTP
  con un solo usuario (los fixtures de cliente de conftest no se pueden combinar
  en un mismo test: el último pisa el override de `get_current_user`).
- Visibilidad por `destino_tipo` y lectura por-usuario: a nivel de servicio, con
  `AuthUser` construidos a mano (mismo enfoque que `test_resumen_territorial` con
  `filtrar_por_visibilidad`).
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.auth import AuthUser
from app.notificaciones import service

BASE = "/api/v1/notificaciones"


@pytest.fixture(autouse=True)
def _mute_audit():
    """`log_audit` hace `CAST(... AS jsonb)` (PostgreSQL) — se mockea para SQLite."""
    with patch("app.notificaciones.service.log_audit", new=AsyncMock()):
        yield


# ── Alta interna + feed HTTP (un solo usuario) ──────────────────────────────

async def _crear(client, **kw):
    body = {"titulo": "t", "mensaje": "m", **kw}
    r = await client.post("/internal/notificaciones", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_listado_vacio(client):
    r = await client.get(BASE)
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "no_leidas": 0}


async def test_alta_interna_y_listado(client):
    nid = await _crear(client, titulo="Hola", mensaje="Mundo", nivel="info")
    data = (await client.get(BASE)).json()
    assert data["total"] == 1
    assert data["no_leidas"] == 1
    item = data["items"][0]
    assert item["id"] == nid
    assert item["titulo"] == "Hola"
    assert item["nivel"] == "info"
    assert item["leida"] is False


async def test_marcar_leida(client):
    nid = await _crear(client)
    await _crear(client)
    r = await client.post(f"{BASE}/{nid}/marcar-leida")
    assert r.status_code == 200
    assert (await client.get(f"{BASE}/no-leidas/contar")).json() == {"no_leidas": 1}
    items = {i["id"]: i["leida"] for i in (await client.get(BASE)).json()["items"]}
    assert items[nid] is True


async def test_marcar_leida_es_idempotente(client):
    nid = await _crear(client)
    await client.post(f"{BASE}/{nid}/marcar-leida")
    r = await client.post(f"{BASE}/{nid}/marcar-leida")
    assert r.status_code == 200
    assert (await client.get(f"{BASE}/no-leidas/contar")).json() == {"no_leidas": 0}


async def test_marcar_leida_inexistente_da_404(client):
    r = await client.post(f"{BASE}/no-existe/marcar-leida")
    assert r.status_code == 404


async def test_marcar_todas_leidas(client):
    for _ in range(3):
        await _crear(client)
    r = await client.post(f"{BASE}/marcar-todas-leidas")
    assert r.status_code == 200
    assert r.json()["marcadas"] == 3
    assert (await client.get(f"{BASE}/no-leidas/contar")).json() == {"no_leidas": 0}
    assert (await client.post(f"{BASE}/marcar-todas-leidas")).json()["marcadas"] == 0


async def test_solo_no_leidas_filtra(client):
    leida = await _crear(client)
    await _crear(client)
    await client.post(f"{BASE}/{leida}/marcar-leida")
    data = (await client.get(BASE, params={"solo_no_leidas": True})).json()
    assert data["total"] == 1
    assert all(i["leida"] is False for i in data["items"])


async def test_invitado_sin_acceso(client_invitado):
    assert (await client_invitado.get(BASE)).status_code == 403


# ── Visibilidad + lectura por-usuario (a nivel de servicio) ─────────────────

_ADMIN = AuthUser(uid="a", email="adm@x", role="Admin", secretarias=[])
_OP_VIV = AuthUser(uid="o", email="opv@x", role="Operador", secretarias=["vivienda"])
_OP_PRIV = AuthUser(uid="p", email="opp@x", role="Operador", secretarias=["privada"])
_CONS = AuthUser(uid="c", email="con@x", role="Consulta", secretarias=["vivienda"])


async def _mk(db, **kw):
    n = await service.crear(db, _ADMIN, {"titulo": "t", "mensaje": "m", **kw})
    return n.id


async def test_visibilidad_global_la_ven_todos(db_session):
    await _mk(db_session, destino_tipo="global")
    for u in (_ADMIN, _OP_VIV, _CONS):
        assert (await service.listar(db_session, u))["total"] == 1


async def test_visibilidad_por_rol(db_session):
    await _mk(db_session, destino_tipo="rol", destino_valor="Operador")
    assert (await service.listar(db_session, _ADMIN))["total"] == 1   # Admin ve todo
    assert (await service.listar(db_session, _OP_VIV))["total"] == 1  # rol coincide
    assert (await service.listar(db_session, _CONS))["total"] == 0    # rol no coincide


async def test_visibilidad_por_secretaria(db_session):
    await _mk(db_session, destino_tipo="secretaria", destino_valor="privada")
    assert (await service.listar(db_session, _OP_PRIV))["total"] == 1
    assert (await service.listar(db_session, _OP_VIV))["total"] == 0
    assert (await service.listar(db_session, _ADMIN))["total"] == 1


async def test_lectura_es_por_usuario(db_session):
    nid = await _mk(db_session, destino_tipo="global")
    await service.marcar_leida(db_session, _OP_VIV, nid)
    assert await service.contar_no_leidas(db_session, _OP_VIV) == 0
    assert await service.contar_no_leidas(db_session, _CONS) == 1
