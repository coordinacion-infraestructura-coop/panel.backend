"""Helpers compartidos entre módulos de svc-privada."""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def norm(value: Any) -> str:
    """UPPER(TRIM(x)) — misma normalización que el sistema viejo para depto/localidad."""
    return str(value or "").strip().upper()


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def dias_transcurridos(fecha_estado: datetime | None) -> int | None:
    """Equivalente a TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), fecha_estado, DAY)."""
    if fecha_estado is None:
        return None
    ref = fecha_estado
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (now_utc() - ref).days
