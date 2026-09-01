"""Unit tests de los helpers de transformación del ETL (scripts/migrar_desde_bigquery.py)."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from migrar_desde_bigquery import d, meta_to_dict, num, s, ts  # noqa: E402


def test_s_normaliza_vacios():
    assert s("") is None
    assert s("   ") is None
    assert s(None) is None
    assert s("x") == "x"
    assert s(0) == 0  # no toca no-strings


def test_ts_aware_utc():
    assert ts(None) is None
    naive = ts("2026-08-31T13:00:00")
    assert naive.tzinfo is not None and naive.utcoffset().total_seconds() == 0
    aware = ts(datetime(2026, 8, 31, tzinfo=timezone.utc))
    assert aware.tzinfo is not None


def test_d_a_date():
    assert d(None) is None
    assert d("2026-08-31") == date(2026, 8, 31)
    assert d(date(2026, 1, 2)) == date(2026, 1, 2)
    assert d(datetime(2026, 8, 31, 5, 0)) == date(2026, 8, 31)


def test_num_decimal():
    assert num(None) is None
    assert str(num("12.50")) == "12.50"
    assert str(num(3)) == "3"


@pytest.mark.parametrize("entrada,esperado", [
    (None, None),
    ({"a": 1}, {"a": 1}),
    ('{"a": 1}', {"a": 1}),
    ("no es json", {"_raw": "no es json"}),
])
def test_meta_to_dict(entrada, esperado):
    assert meta_to_dict(entrada) == esperado
