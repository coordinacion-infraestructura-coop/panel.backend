"""Tests de integración para el módulo portal (gestión de usuarios)."""
import pytest
from httpx import AsyncClient

BASE = "/api/v1/portal"
ADMIN_BASE = f"{BASE}/admin/usuarios"

_USUARIO_BASE = {
    "email": "nuevo@test.com",
    "nombre": "Usuario Test",
    "rol": "Operador",
    "secretarias": ["vivienda"],
}


# ── /me ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_me_devuelve_403_si_no_registrado(client: AsyncClient):
    """El usuario admin del test no está en portal_usuarios → 403."""
    r = await client.get(f"{BASE}/me")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "USUARIO_NO_REGISTRADO"


@pytest.mark.asyncio
async def test_get_me_devuelve_datos_si_registrado(client: AsyncClient):
    await client.post(ADMIN_BASE, json={
        "email": "admin@test.com",  # mismo email que ADMIN_USER del conftest
        "rol": "Admin",
        "secretarias": ["vivienda"],
    })
    r = await client.get(f"{BASE}/me")
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == "admin@test.com"
    assert data["rol"] == "Admin"


# ── CRUD usuarios (requiere Admin) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crear_usuario(client: AsyncClient):
    r = await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "nuevo@test.com"
    assert data["rol"] == "Operador"
    assert "vivienda" in data["secretarias"]
    assert data["activo"] is True


@pytest.mark.asyncio
async def test_listar_usuarios(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    await client.post(ADMIN_BASE, json={**_USUARIO_BASE, "email": "otro@test.com"})

    r = await client.get(ADMIN_BASE)
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_get_usuario_por_email(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)

    r = await client.get(f"{ADMIN_BASE}/nuevo@test.com")
    assert r.status_code == 200
    assert r.json()["email"] == "nuevo@test.com"


@pytest.mark.asyncio
async def test_get_usuario_inexistente(client: AsyncClient):
    r = await client.get(f"{ADMIN_BASE}/noexiste@test.com")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_email_duplicado_devuelve_409(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    r = await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EMAIL_DUPLICADO"


@pytest.mark.asyncio
async def test_email_se_normaliza_a_minusculas(client: AsyncClient):
    r = await client.post(ADMIN_BASE, json={**_USUARIO_BASE, "email": "MAYUS@Test.COM"})
    assert r.status_code == 201
    assert r.json()["email"] == "mayus@test.com"


# ── Validación de roles ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rol_invalido_devuelve_422(client: AsyncClient):
    r = await client.post(ADMIN_BASE, json={**_USUARIO_BASE, "rol": "SuperAdmin"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ROL_INVALIDO"


@pytest.mark.asyncio
async def test_roles_validos_son_aceptados(client: AsyncClient):
    for i, rol in enumerate(["Admin", "Supervisor", "Operador", "Consulta"]):
        r = await client.post(ADMIN_BASE, json={
            **_USUARIO_BASE,
            "email": f"user{i}@test.com",
            "rol": rol,
        })
        assert r.status_code == 201, f"Rol {rol} no aceptado: {r.text}"


# ── Validación de secretarías (Bug 2 fix) ────────────────────────────────────

@pytest.mark.asyncio
async def test_secretaria_invalida_devuelve_422(client: AsyncClient):
    """Bug 2 fix: secretarías deben validarse contra SECRETARIAS_VALIDAS."""
    r = await client.post(ADMIN_BASE, json={
        **_USUARIO_BASE,
        "secretarias": ["vivienda", "hackers"],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_secretarias_validas_son_aceptadas(client: AsyncClient):
    r = await client.post(ADMIN_BASE, json={
        **_USUARIO_BASE,
        "secretarias": ["vivienda", "privada", "infraestructura"],
    })
    assert r.status_code == 201
    assert set(r.json()["secretarias"]) == {"vivienda", "privada", "infraestructura"}


@pytest.mark.asyncio
async def test_sin_secretarias_es_valido(client: AsyncClient):
    r = await client.post(ADMIN_BASE, json={**_USUARIO_BASE, "secretarias": []})
    assert r.status_code == 201


# ── Actualizar usuario ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_actualizar_nombre(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    r = await client.put(f"{ADMIN_BASE}/nuevo@test.com", json={"nombre": "Nombre Nuevo"})
    assert r.status_code == 200
    assert r.json()["nombre"] == "Nombre Nuevo"


@pytest.mark.asyncio
async def test_actualizar_rol(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    r = await client.put(f"{ADMIN_BASE}/nuevo@test.com", json={"rol": "Supervisor"})
    assert r.status_code == 200
    assert r.json()["rol"] == "Supervisor"


@pytest.mark.asyncio
async def test_actualizar_rol_invalido(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    r = await client.put(f"{ADMIN_BASE}/nuevo@test.com", json={"rol": "Hacker"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_actualizar_secretarias_reemplaza(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    r = await client.put(f"{ADMIN_BASE}/nuevo@test.com", json={"secretarias": ["privada"]})
    assert r.status_code == 200
    assert r.json()["secretarias"] == ["privada"]


@pytest.mark.asyncio
async def test_actualizar_secretaria_invalida(client: AsyncClient):
    """Bug 2 fix también aplica al update."""
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    r = await client.put(f"{ADMIN_BASE}/nuevo@test.com", json={"secretarias": ["hacker"]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_desactivar_usuario(client: AsyncClient):
    await client.post(ADMIN_BASE, json=_USUARIO_BASE)
    r = await client.put(f"{ADMIN_BASE}/nuevo@test.com", json={"activo": False})
    assert r.status_code == 200
    assert r.json()["activo"] is False


@pytest.mark.asyncio
async def test_actualizar_usuario_inexistente(client: AsyncClient):
    r = await client.put(f"{ADMIN_BASE}/noexiste@test.com", json={"nombre": "X"})
    assert r.status_code == 404


# ── Control de acceso (solo Admin puede gestionar usuarios) ──────────────────

@pytest.mark.asyncio
async def test_operador_no_puede_listar_usuarios(client_operador: AsyncClient):
    r = await client_operador.get(ADMIN_BASE)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_operador_no_puede_crear_usuario(client_operador: AsyncClient):
    r = await client_operador.post(ADMIN_BASE, json=_USUARIO_BASE)
    assert r.status_code == 403
