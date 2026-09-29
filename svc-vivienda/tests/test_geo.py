"""Tests del módulo `geo` — resolución de localidades (ADR-024,
spec-normalizacion-localidades.md) y detección de duplicados existentes."""
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordon_cuneta.models import MunicipioCordonCuneta
from app.geo import service as geo_service
from app.geo.models import GeoAliasManual, GeoLocalidad

DUPLICADOS_URL = "/api/v1/vivienda/geo/duplicados"


@pytest_asyncio.fixture
async def geo_seed(db_session: AsyncSession) -> None:
    db_session.add_all([
        GeoLocalidad(id_geo="443", departamento="Río Cuarto", localidad="Paso del Durazno", activo=True),
        GeoLocalidad(id_geo="158", departamento="Punilla", localidad="Icho Cruz", activo=True),
        GeoLocalidad(id_geo="999", departamento="Colón", localidad="Villa Retirada", activo=False),
    ])
    db_session.add_all([
        GeoAliasManual(
            id=str(uuid.uuid4()),
            texto_normalizado="santiago temple",
            texto_original="Santiago Temple",
            id_geo=None,
            motivo="confirmada ausente del padrón",
            origen="atp",
        ),
        GeoAliasManual(
            id=str(uuid.uuid4()),
            texto_normalizado="icho cruz pueblo",
            texto_original="Icho Cruz Pueblo",
            id_geo="158",
            motivo="alias local sin relación textual con el nombre oficial",
            origen="gas_pit",
        ),
    ])
    await db_session.flush()


# ── geo/service.py — resolución, sin HTTP ────────────────────────────────────

@pytest.mark.asyncio
async def test_resolver_uno_match_exacto(db_session: AsyncSession, geo_seed):
    r = await geo_service.resolver_uno(db_session, "Río Cuarto", "Paso del Durazno")
    assert r.id_geo == "443"
    assert r.match_tipo == "exacto"
    assert r.localidad_oficial == "Paso del Durazno"


@pytest.mark.asyncio
async def test_resolver_uno_match_por_alias_paren_guion(db_session: AsyncSession, geo_seed):
    r = await geo_service.resolver_uno(db_session, "Punilla", "Villa Río Icho Cruz - Icho Cruz")
    assert r.id_geo == "158"
    assert r.match_tipo == "alias"


@pytest.mark.asyncio
async def test_resolver_uno_departamento_incorrecto_no_bloquea_match(db_session: AsyncSession, geo_seed):
    # Único candidato por nombre → matchea aunque el departamento de entrada
    # sea distinto al del padrón (mismo criterio que el caso real "Paso del
    # Durazno" de spec-sync-atp-compromiso-gobernador.md §12.9).
    r = await geo_service.resolver_uno(db_session, "Juárez Celman", "Paso Del Durazno")
    assert r.id_geo == "443"


@pytest.mark.asyncio
async def test_resolver_uno_vinculacion_manual_sin_id_geo(db_session: AsyncSession, geo_seed):
    r = await geo_service.resolver_uno(db_session, "Río Segundo", "Santiago Temple")
    assert r.id_geo is None
    assert r.match_tipo == "manual"


@pytest.mark.asyncio
async def test_resolver_uno_manual_con_id_geo_completa_grafia_oficial(db_session: AsyncSession, geo_seed):
    r = await geo_service.resolver_uno(db_session, None, "Icho Cruz Pueblo")
    assert r.id_geo == "158"
    assert r.match_tipo == "manual"
    assert r.localidad_oficial == "Icho Cruz"
    assert r.departamento_oficial == "Punilla"


@pytest.mark.asyncio
async def test_resolver_uno_matchea_alias_del_padron_sin_alias_en_la_fuente(db_session: AsyncSession):
    """El padrón puede traer su propio alias entre paréntesis (ej. "CHARRAS
    (Villa Colón)") — una fuente que sólo escribe "CHARRAS" debe matchear
    igual (bug real encontrado 2026-09-28, ver migración 0031)."""
    from app.geo.models import GeoLocalidad
    db_session.add(GeoLocalidad(
        id_geo="88", departamento="Juárez Celman", localidad="CHARRAS (Villa Colón)", activo=True,
    ))
    await db_session.flush()
    r = await geo_service.resolver_uno(db_session, "Juárez Celman", "CHARRAS")
    assert r.id_geo == "88"
    # "exacto" porque el texto de entrada no necesitó su propia expansión de
    # alias (ver docstring de _cargar_padron) — el alias estaba del lado del
    # padrón, no del lado de la fuente.
    assert r.match_tipo == "exacto"


@pytest.mark.asyncio
async def test_resolver_uno_desambigua_con_departamento_abreviado(db_session: AsyncSession):
    """normalize_departamento colapsa "General"->"Gral" para la desambiguación
    por departamento — el Sheet suele traer el nombre completo, el padrón la
    forma abreviada."""
    from app.geo.models import GeoLocalidad
    db_session.add_all([
        GeoLocalidad(id_geo="1", departamento="Gral Roca", localidad="Homónima", activo=True),
        GeoLocalidad(id_geo="2", departamento="Río Cuarto", localidad="Homónima", activo=True),
    ])
    await db_session.flush()
    r = await geo_service.resolver_uno(db_session, "General Roca", "Homónima")
    assert r.id_geo == "1"


@pytest.mark.asyncio
async def test_resolver_uno_alias_con_caracter_espurio_en_el_dato_de_origen(db_session: AsyncSession):
    """Regresión: un carácter espurio (U+2018) insertado en el dato de
    Privada para 'Chuña' rompía normalize_name — se resuelve igual vía
    vinculación manual explícita (migración 0032)."""
    db_session.add(GeoLocalidad(id_geo="553", departamento="Ischilín", localidad="Chuña", activo=True))
    db_session.add(GeoAliasManual(
        id=str(uuid.uuid4()),
        texto_normalizado="chun‘a",
        texto_original="CHUÑ‘A",
        id_geo="553",
        motivo="carácter espurio en el dato de origen",
        origen="privada",
    ))
    await db_session.flush()
    r = await geo_service.resolver_uno(db_session, "Ischilín", "CHUÑ‘A")
    assert r.id_geo == "553"
    assert r.match_tipo == "manual"


@pytest.mark.asyncio
async def test_resolver_uno_sin_match(db_session: AsyncSession, geo_seed):
    r = await geo_service.resolver_uno(db_session, "Capital", "Localidad Inexistente")
    assert r.id_geo is None
    assert r.match_tipo == "sin_match"


@pytest.mark.asyncio
async def test_resolver_uno_localidad_vacia_es_sin_match(db_session: AsyncSession, geo_seed):
    r = await geo_service.resolver_uno(db_session, "Capital", None)
    assert r.match_tipo == "sin_match"


@pytest.mark.asyncio
async def test_resolver_uno_no_matchea_geo_inactivo(db_session: AsyncSession, geo_seed):
    r = await geo_service.resolver_uno(db_session, "Colón", "Villa Retirada")
    assert r.id_geo is None
    assert r.match_tipo == "sin_match"


@pytest.mark.asyncio
async def test_resolver_lote_resuelve_varios_en_una_carga(db_session: AsyncSession, geo_seed):
    resultados = await geo_service.resolver_lote(db_session, [
        ("Río Cuarto", "Paso del Durazno"),
        ("Punilla", "Icho Cruz"),
        ("Capital", "Nada"),
    ])
    assert [r.match_tipo for r in resultados] == ["exacto", "exacto", "sin_match"]


# ── geo/service.py — notificación de localidades sin resolver (2026-09-29) ──

@pytest.mark.asyncio
async def test_resolver_lote_sin_match_crea_una_notificacion_batcheada(db_session: AsyncSession, geo_seed):
    from sqlalchemy import select
    from app.notificaciones.models import Notificacion

    await geo_service.resolver_lote(
        db_session,
        [("Río Cuarto", "Paso del Durazno"), ("Capital", "Nada"), ("Capital", "Otra Inexistente")],
        origen="gas_pit",
    )
    notifs = (await db_session.execute(select(Notificacion))).scalars().all()
    assert len(notifs) == 1
    n = notifs[0]
    assert n.nivel == "advertencia"
    assert n.destino_tipo == "rol"
    assert n.destino_valor == "Admin"
    assert n.origen == "geo_resolver"
    assert "gas_pit" in n.titulo
    assert "Nada" in n.mensaje and "Otra Inexistente" in n.mensaje


@pytest.mark.asyncio
async def test_resolver_lote_todo_resuelto_no_crea_notificacion(db_session: AsyncSession, geo_seed):
    from sqlalchemy import select
    from app.notificaciones.models import Notificacion

    await geo_service.resolver_lote(
        db_session, [("Río Cuarto", "Paso del Durazno")], origen="atp",
    )
    notifs = (await db_session.execute(select(Notificacion))).scalars().all()
    assert notifs == []


@pytest.mark.asyncio
async def test_resolver_uno_sin_match_propaga_origen_a_la_notificacion(db_session: AsyncSession, geo_seed):
    from sqlalchemy import select
    from app.notificaciones.models import Notificacion

    await geo_service.resolver_uno(db_session, "Capital", "Localidad Inexistente", origen="cordon_cuneta")
    notifs = (await db_session.execute(select(Notificacion))).scalars().all()
    assert len(notifs) == 1
    assert "cordon_cuneta" in notifs[0].titulo


# ── geo/service.py — detección de duplicados ─────────────────────────────────

@pytest.mark.asyncio
async def test_detectar_duplicados_agrupa_variantes(db_session: AsyncSession):
    db_session.add_all([
        MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=1, municipio="Villa Dolores", departamento="San Javier"),
        MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=2, municipio="VILLA DOLORES", departamento="San Javier"),
        MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=3, municipio="Río Tercero", departamento="Tercero Arriba"),
    ])
    await db_session.flush()
    grupos = await geo_service.detectar_duplicados(db_session, "cordon_cuneta")
    assert len(grupos) == 1
    assert grupos[0]["normalizado"] == "villa dolores"
    assert {v["texto"] for v in grupos[0]["variantes"]} == {"Villa Dolores", "VILLA DOLORES"}


@pytest.mark.asyncio
async def test_detectar_duplicados_sin_duplicados_no_devuelve_grupos(db_session: AsyncSession):
    db_session.add(MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=1, municipio="Única", departamento="Capital"))
    await db_session.flush()
    grupos = await geo_service.detectar_duplicados(db_session, "cordon_cuneta")
    assert grupos == []


@pytest.mark.asyncio
async def test_detectar_duplicados_ignora_filas_borradas(db_session: AsyncSession):
    from datetime import datetime, timezone
    db_session.add_all([
        MunicipioCordonCuneta(id=str(uuid.uuid4()), orden=1, municipio="Villa X", departamento="D"),
        MunicipioCordonCuneta(
            id=str(uuid.uuid4()), orden=2, municipio="VILLA X", departamento="D",
            deleted_at=datetime.now(timezone.utc),
        ),
    ])
    await db_session.flush()
    grupos = await geo_service.detectar_duplicados(db_session, "cordon_cuneta")
    assert grupos == []


# ── GET /api/v1/vivienda/geo/duplicados — HTTP, gateado a Admin/Supervisor ──

@pytest.mark.asyncio
async def test_duplicados_endpoint_admin_ok(client: AsyncClient):
    r = await client.get(DUPLICADOS_URL, params={"modulo": "cordon_cuneta"})
    assert r.status_code == 200
    assert r.json() == {"grupos": []}


@pytest.mark.asyncio
async def test_duplicados_endpoint_operador_403(client_operador: AsyncClient):
    r = await client_operador.get(DUPLICADOS_URL, params={"modulo": "cordon_cuneta"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_duplicados_endpoint_modulo_invalido_422(client: AsyncClient):
    r = await client.get(DUPLICADOS_URL, params={"modulo": "no-existe"})
    assert r.status_code == 422
