import pytest

from app.agente.sql_guard import SqlRechazado, validar


def ok(sql: str, limite: int = 500) -> str:
    return validar(sql, limite=limite).sql


@pytest.mark.parametrize("sql", [
    "SELECT * FROM ag_localidades",
    "SELECT departamento, COUNT(*) FROM ag.ag_gestiones GROUP BY departamento",
    "WITH x AS (SELECT id_geo FROM ag_programa_items) SELECT * FROM x JOIN ag_localidades l USING (id_geo)",
    "SELECT localidad FROM ag_localidades UNION SELECT localidad FROM ag_gestiones",
    "SELECT detalle FROM ag_gestiones WHERE detalle ILIKE '%ambulancia%'",
])
def test_select_validos(sql):
    out = ok(sql)
    assert "LIMIT 500" in out


@pytest.mark.parametrize("sql,motivo", [
    ("DELETE FROM ag_gestiones", "SELECT"),
    ("UPDATE ag_gestiones SET estado = 'X'", "SELECT"),
    ("DROP TABLE ag_gestiones", "SELECT"),
    ("SELECT 1; DELETE FROM ag_gestiones", "una sola"),
    ("SELECT * FROM ag_conversaciones", "no permitida"),
    ("SELECT * FROM viv_beneficiarios", "no permitida"),
    ("SELECT * FROM public.ag_localidades", "no permitida"),
    ("SELECT * FROM pg_catalog.pg_roles", "no permitida"),
    ("SELECT * FROM information_schema.tables", "no permitida"),
    ("SELECT pg_read_file('/etc/passwd')", "Función"),
    ("SELECT pg_sleep(100)", "Función"),
    ("SELECT set_config('statement_timeout', '0', false)", "Función"),
    ("SELECT current_setting('is_superuser')", "Función"),
    ("WITH d AS (DELETE FROM ag_gestiones RETURNING *) SELECT * FROM d", "no permitida"),
    ("SELECT * INTO nueva FROM ag_gestiones", "no permitida"),
    ("SELECT * FROM otra_base.ag.ag_localidades", "otra base"),
    ("", "vacía"),
    ("ESTO NO ES SQL", ""),
])
def test_rechazos(sql, motivo):
    with pytest.raises(SqlRechazado) as e:
        validar(sql, limite=500)
    assert motivo.lower() in str(e.value).lower()


def test_limit_se_recorta_y_respeta():
    assert "LIMIT 500" in ok("SELECT * FROM ag_localidades LIMIT 10000")
    assert "LIMIT 10" in ok("SELECT * FROM ag_localidades LIMIT 10")


def test_tablas_se_califican_con_schema_ag():
    assert "ag.ag_localidades" in ok("SELECT * FROM ag_localidades")


def test_cte_con_nombre_de_tabla_permitida_no_escapa():
    # Un CTE no puede "tapar" una tabla real fuera de ag: la referencia calificada se valida.
    with pytest.raises(SqlRechazado):
        validar("WITH ag_localidades AS (SELECT 1) SELECT * FROM public.viv_beneficiarios", limite=10)
