"""Spec §4: los datos personales quedan fuera por GRANT. Los grants se generan desde los
extractores; este test falla si un extractor empieza a leer una columna excluida."""
import importlib.util
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("generar_grants", _RAIZ / "sql" / "generar_grants.py")
gg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gg)

from app.etl.extractores import FUENTES  # noqa: E402

EXCLUIDAS = {
    "priv_gestiones": {"direccion", "lat", "lon", "created_by", "updated_by", "observaciones"},
    "priv_gestiones_eventos": {"usuario", "rol_usuario", "comentario", "valor_anterior", "valor_nuevo"},
    "atp_interno_pagos": {"referente"},
    "ext_gob_intendente": {"celular"},
}
TABLAS_PROHIBIDAS = {"viv_beneficiarios", "portal_usuarios", "portal_usuario_secretarias",
                     "portal_usuario_areas", "portal_notificaciones", "ext_gob_intendente"}


def _por_tabla():
    out = {}
    for consultas in FUENTES.values():
        for sql in consultas.values():
            for t, cols in gg.columnas_por_tabla(sql).items():
                out.setdefault(t, set()).update(cols)
    return out


def test_ningun_extractor_lee_columnas_personales():
    por_tabla = _por_tabla()
    for tabla, excluidas in EXCLUIDAS.items():
        assert not (por_tabla.get(tabla, set()) & excluidas), tabla
    assert not (set(por_tabla) & TABLAS_PROHIBIDAS)


def test_ningun_extractor_usa_select_estrella():
    for consultas in FUENTES.values():
        for sql in consultas.values():
            assert "*" not in sql


def test_grants_commiteados_coinciden_con_extractores(capsys):
    gg.main()
    generado = capsys.readouterr().out
    commiteado = (_RAIZ / "sql" / "grants_fuentes.sql").read_text(encoding="utf-8")
    assert generado.strip() == commiteado.strip(), "Regenerar: python sql/generar_grants.py > sql/grants_fuentes.sql"
