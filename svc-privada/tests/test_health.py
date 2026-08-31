import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "svc-privada"


@pytest.mark.asyncio
async def test_schema_tables_created(db_session):
    """La migración 0001 (vía Base.metadata) crea las tablas priv_* esperadas."""
    from sqlalchemy import inspect
    from tests.conftest import test_engine

    def _tables(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    async with test_engine.connect() as conn:
        tables = await conn.run_sync(_tables)
    for t in (
        "priv_gestiones",
        "priv_gestiones_eventos",
        "priv_localidades_info",
        "priv_departamentos_info",
        "priv_geo_localidades",
        "priv_cat_estado",
        "priv_cat_categoria_general",
    ):
        assert t in tables, f"falta la tabla {t}"
