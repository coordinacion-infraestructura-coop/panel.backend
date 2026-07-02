"""Tests de integración para el módulo beneficiarios."""
import pytest
from httpx import AsyncClient


BASE = "/api/v1/vivienda/beneficiarios"

_BENE_BASE = {
    "dni": "12345678",
    "nombre": "Juan",
    "apellido": "Pérez",
    "telefono": "3512345678",
}


# ── CRUD básico ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_beneficiario(client: AsyncClient):
    r = await client.post(BASE, json=_BENE_BASE)
    assert r.status_code == 201
    data = r.json()
    assert data["dni"] == "12345678"
    assert data["nombre"] == "Juan"
    assert "id" in data


@pytest.mark.asyncio
async def test_listar_beneficiarios_vacio(client: AsyncClient):
    r = await client.get(BASE)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["data"] == []


@pytest.mark.asyncio
async def test_listar_beneficiarios_con_datos(client: AsyncClient):
    await client.post(BASE, json=_BENE_BASE)
    await client.post(BASE, json={**_BENE_BASE, "dni": "99999999", "nombre": "Ana"})

    r = await client.get(BASE)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_get_beneficiario_por_id(client: AsyncClient):
    cr = await client.post(BASE, json=_BENE_BASE)
    bid = cr.json()["id"]

    r = await client.get(f"{BASE}/{bid}")
    assert r.status_code == 200
    assert r.json()["id"] == bid


@pytest.mark.asyncio
async def test_get_beneficiario_inexistente(client: AsyncClient):
    r = await client.get(f"{BASE}/no-existe-uuid")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_buscar_por_dni(client: AsyncClient):
    await client.post(BASE, json=_BENE_BASE)

    r = await client.get(f"{BASE}/buscar", params={"dni": "12345678"})
    assert r.status_code == 200
    assert r.json()["dni"] == "12345678"


@pytest.mark.asyncio
async def test_buscar_por_dni_inexistente(client: AsyncClient):
    r = await client.get(f"{BASE}/buscar", params={"dni": "00000000"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_actualizar_beneficiario(client: AsyncClient):
    cr = await client.post(BASE, json=_BENE_BASE)
    bid = cr.json()["id"]

    r = await client.patch(f"{BASE}/{bid}", json={"nombre": "Carlos"})
    assert r.status_code == 200
    assert r.json()["nombre"] == "Carlos"
    assert r.json()["apellido"] == "Pérez"  # campo no modificado


@pytest.mark.asyncio
async def test_actualizar_beneficiario_inexistente(client: AsyncClient):
    r = await client.patch(f"{BASE}/no-existe", json={"nombre": "X"})
    assert r.status_code == 404


# ── DNI único ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_dni_duplicado_devuelve_409(client: AsyncClient):
    await client.post(BASE, json=_BENE_BASE)
    r = await client.post(BASE, json={**_BENE_BASE, "nombre": "Pedro"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "VALIDACION_FALLIDA"


# ── Soft delete ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eliminar_beneficiario_requiere_admin(client_operador: AsyncClient):
    """Bug 1 fix: DELETE debe requerir rol Admin, no Operador."""
    cr = await client_operador.post(BASE, json=_BENE_BASE)
    # Operador puede crear pero NO eliminar
    bid = cr.json()["id"]
    r = await client_operador.delete(f"{BASE}/{bid}")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_eliminar_beneficiario_admin_ok(client: AsyncClient):
    cr = await client.post(BASE, json=_BENE_BASE)
    bid = cr.json()["id"]

    r = await client.delete(f"{BASE}/{bid}")
    assert r.status_code == 204

    # Tras soft-delete, no debe encontrarse
    r2 = await client.get(f"{BASE}/{bid}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_soft_delete_no_aparece_en_listado(client: AsyncClient):
    cr = await client.post(BASE, json=_BENE_BASE)
    bid = cr.json()["id"]
    await client.delete(f"{BASE}/{bid}")

    r = await client.get(BASE)
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_soft_delete_bloquea_reutilizacion_de_dni(client: AsyncClient):
    """Un DNI soft-deleted no puede reutilizarse: la UNIQUE constraint aplica a todos los registros."""
    cr = await client.post(BASE, json=_BENE_BASE)
    bid = cr.json()["id"]
    await client.delete(f"{BASE}/{bid}")

    r = await client.post(BASE, json={**_BENE_BASE, "nombre": "Nuevo"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "VALIDACION_FALLIDA"


# ── Búsqueda por texto ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_busqueda_por_nombre(client: AsyncClient):
    await client.post(BASE, json=_BENE_BASE)
    await client.post(BASE, json={**_BENE_BASE, "dni": "88888888", "nombre": "Roberto"})

    r = await client.get(BASE, params={"q": "Juan"})
    assert r.json()["total"] == 1
    assert r.json()["data"][0]["nombre"] == "Juan"


@pytest.mark.asyncio
async def test_busqueda_por_apellido(client: AsyncClient):
    await client.post(BASE, json=_BENE_BASE)

    r = await client.get(BASE, params={"q": "Pérez"})
    assert r.json()["total"] == 1


# ── Control de acceso ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lectura_permitida_para_consulta(client_consulta: AsyncClient):
    r = await client_consulta.get(BASE)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_escritura_denegada_para_consulta(client_consulta: AsyncClient):
    r = await client_consulta.post(BASE, json=_BENE_BASE)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sin_token_devuelve_401(client_invitado: AsyncClient):
    """Rol invitado no tiene acceso ni a lectura."""
    r = await client_invitado.get(BASE)
    assert r.status_code == 403
