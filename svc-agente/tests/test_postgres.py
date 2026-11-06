"""Integración contra Postgres real (spec §2.3, §10). SQLite no reproduce los permisos de rol, el
read-only ni el timeout, y oculta diferencias de dialecto en el SQL de los indicadores.

Se saltea salvo que estén definidas las dos URLs, apuntando a una base creada con
sql/roles_db_agente.sql y migrada con `alembic upgrade head` (nunca producción):

  AGENTE_PG_APP_URL=postgresql+asyncpg://agente_app:...@localhost:5437/db_agente
  AGENTE_PG_LLM_URL=postgresql+asyncpg://agente_llm:...@localhost:5437/db_agente
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.agente.herramientas import Turno, ejecutar, ejecutar_sql
from app.config import settings
from app.semantica.glosario import glosario
from tests.conftest import HOY, lector_de, raw_fuentes

APP_URL = os.environ.get("AGENTE_PG_APP_URL")
LLM_URL = os.environ.get("AGENTE_PG_LLM_URL")
pytestmark = pytest.mark.skipif(not (APP_URL and LLM_URL), reason="sin Postgres de integración")


@pytest_asyncio.fixture
async def pg_db():
    eng = create_async_engine(APP_URL, poolclass=NullPool)
    async with AsyncSession(eng, expire_on_commit=False) as s:
        from app.etl.carga import refrescar
        await refrescar(s, lector_de(raw_fuentes()), hoy=HOY)
        await s.commit()
        yield s
    await eng.dispose()


@pytest_asyncio.fixture
async def pg_llm():
    eng = create_async_engine(LLM_URL, poolclass=NullPool)
    async with AsyncSession(eng) as s:
        yield s
    await eng.dispose()


async def test_etl_dos_veces_reemplaza(pg_db):
    from app.etl.carga import refrescar
    antes = (await pg_db.execute(text("SELECT COUNT(*) FROM ag.ag_programa_items"))).scalar()
    await refrescar(pg_db, lector_de(raw_fuentes()), hoy=HOY)
    await pg_db.commit()
    assert (await pg_db.execute(text("SELECT COUNT(*) FROM ag.ag_programa_items"))).scalar() == antes > 0


@pytest.mark.parametrize("tool,args", [
    ("resolver_territorio", {"texto": "villa maria"}),
    ("estado_programa_territorio", {"programa": "cc", "departamento": "San Justo", "id_geo": None}),
    ("estado_programa_territorio", {"programa": None, "departamento": None, "id_geo": None}),
    ("ficha_territorio", {"departamento": "San Justo", "id_geo": None}),
    ("montos", {"programa": None, "departamento": None, "id_geo": None, "desde": "2025-01-01", "hasta": None}),
    ("pendientes", {"tipo": "gestiones", "umbral_dias": None, "departamento": None, "id_geo": None, "programa": None}),
    ("pendientes", {"tipo": "programas", "umbral_dias": 30, "departamento": None, "id_geo": None, "programa": None}),
    ("pendientes", {"tipo": "hitos", "umbral_dias": None, "departamento": None, "id_geo": None, "programa": None}),
])
async def test_indicadores_corren_en_postgres(pg_db, pg_llm, tool, args):
    res = await ejecutar(tool, args, pg_db, pg_llm, Turno())
    assert "error" not in res, res


@pytest.mark.parametrize("i", range(len(glosario()["ejemplos_sql"])))
async def test_ejemplos_sql_del_glosario_corren_con_agente_llm(pg_db, pg_llm, i):
    ej = glosario()["ejemplos_sql"][i]
    res = await ejecutar_sql(pg_llm, ej["sql"], Turno())
    assert "error" not in res, (ej["pregunta"], res)


@pytest.mark.parametrize("sql", [
    "INSERT INTO ag.ag_frescura (fuente, estado) VALUES ('x', 'ok')",
    "DELETE FROM ag.ag_programa_items",
    "SELECT * FROM public.ag_mensajes",
    "SELECT * FROM public.ag_interacciones",
    "CREATE TABLE ag.x (a int)",
])
async def test_rol_llm_no_escribe_ni_lee_public_aunque_se_saltee_el_validador(pg_db, pg_llm, sql):
    with pytest.raises(Exception, match="permission denied|read-only"):
        await pg_llm.execute(text(sql))
    await pg_llm.rollback()


async def test_rol_llm_tiene_search_path_y_read_only(pg_llm):
    assert (await pg_llm.execute(text("SHOW search_path"))).scalar() == "ag"
    assert (await pg_llm.execute(text("SHOW default_transaction_read_only"))).scalar() == "on"


async def test_timeout_corta_la_consulta(pg_db, pg_llm, monkeypatch):
    monkeypatch.setattr(settings, "sql_timeout_ms", 300)
    # pg_sleep lo rechaza el validador; un producto cartesiano grande no.
    sql = ("SELECT COUNT(*) FROM ag_programa_items a, ag_programa_items b, ag_programa_items c, "
           "ag_programa_items d, ag_programa_items e, ag_programa_items f, ag_programa_items g")
    res = await ejecutar_sql(pg_llm, sql, Turno())
    assert "statement timeout" in res.get("error", "") or "cancel" in res.get("error", ""), res
