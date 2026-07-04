"""Migrate obs → pedidos, doc_exp date entries → estado historial; clear obs fields

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-04 00:00:00.000000
"""

import re
import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TODAY = date(2026, 7, 4)


def _parse_obs(obs: str) -> list[tuple[int, int, str]]:
    """
    Parse obs field into [(day, month, text), ...].
    Handles "DD/MM text", "DD y DD/MM text" (two dates), and no-date lines (→ TODAY).
    Splits on newlines first.
    """
    results = []
    for line in obs.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # "26 y 29/6 se envian correcciones"
        m = re.match(r"^(\d{1,2})\s+y\s+(\d{1,2})/(\d{1,2})\s+(.+)$", line, re.IGNORECASE)
        if m:
            d1, d2 = int(m.group(1)), int(m.group(2))
            mo, text = int(m.group(3)), m.group(4).strip()
            for day in (d1, d2):
                if 1 <= day <= 31 and 1 <= mo <= 12:
                    results.append((day, mo, text))
            continue
        # "DD/MM text"
        m = re.match(r"^(\d{1,2})/(\d{1,2})\s+(.+)$", line)
        if m:
            day, mo, text = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            if 1 <= day <= 31 and 1 <= mo <= 12:
                results.append((day, mo, text))
                continue
        # No date pattern → use TODAY
        results.append((TODAY.day, TODAY.month, line))
    return results


def _parse_doc_exp(doc_exp: str) -> list[tuple[int, int, str]]:
    """
    Extract (day, month, description) tuples from doc_exp entries that contain a date.
    Handles "DD/MM text", "text DD/MM", and " - " separated multi-event strings.
    Returns empty list if no date pattern found.
    """
    if not doc_exp or not doc_exp.strip():
        return []

    def _parse_part(part: str):
        part = part.strip()
        if not part:
            return None
        # "DD/MM text"
        m = re.match(r"^(\d{1,2})/(\d{1,2})\s+(.+)$", part)
        if m:
            d, mo, desc = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            if 1 <= d <= 31 and 1 <= mo <= 12:
                return (d, mo, desc)
        # "text DD/MM" (e.g. "TC 17/6")
        m = re.match(r"^(.+)\s+(\d{1,2})/(\d{1,2})$", part)
        if m:
            desc, d, mo = m.group(1).strip(), int(m.group(2)), int(m.group(3))
            if 1 <= d <= 31 and 1 <= mo <= 12:
                return (d, mo, desc)
        # Embedded date (e.g. "Vuelve el 26/6 para GEOLOCALIZACION")
        m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", part)
        if m:
            d, mo = int(m.group(1)), int(m.group(2))
            if 1 <= d <= 31 and 1 <= mo <= 12:
                desc = re.sub(r"\d{1,2}/\d{1,2}", "", part)
                desc = re.sub(r"\s+", " ", desc).strip(" -")
                return (d, mo, desc)
        return None

    parts = doc_exp.strip().split(" - ")
    if len(parts) > 1:
        return [r for p in parts if (r := _parse_part(p))]
    r = _parse_part(doc_exp.strip())
    return [r] if r else []


def _clean_doc_exp(doc_exp: str) -> str | None:
    """Strip date prefix/suffix from doc_exp, keeping the descriptive part."""
    if not doc_exp:
        return doc_exp
    text = doc_exp.strip()
    text = re.sub(r"^\d{1,2}/\d{1,2}\s+", "", text)          # "DD/MM " prefix
    text = re.sub(r"\s+\d{1,2}/\d{1,2}$", "", text)           # " DD/MM" suffix
    text = re.sub(r"\s+el\s+\d{1,2}/\d{1,2}\s+", " ", text)   # "el DD/MM" in middle
    text = re.sub(r"\s+\d{1,2}/\d{1,2}\s+", " ", text)        # any remaining " DD/MM "
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text if text else None


def _find_estado_id(conn, tabla_estados: str, description: str):
    """Map a description to an estado id by keyword matching."""
    desc_l = description.lower()
    label = None
    if re.search(r"\btc\b", desc_l):
        label = "tc"
    elif "notifica" in desc_l:
        label = "notificado"
    elif "firma convenio" in desc_l or "firma el convenio" in desc_l:
        label = "convenio firmado"
    if not label:
        return None
    row = conn.execute(
        sa.text(f"SELECT id FROM {tabla_estados} WHERE LOWER(label) = :l ORDER BY orden LIMIT 1"),
        {"l": label},
    ).fetchone()
    return row[0] if row else None


def _find_prev_estado_id(conn, tabla_estados: str, estado_id: int):
    row = conn.execute(
        sa.text(f"""
            SELECT id FROM {tabla_estados}
            WHERE orden < (SELECT orden FROM {tabla_estados} WHERE id = :id)
            ORDER BY orden DESC LIMIT 1
        """),
        {"id": estado_id},
    ).fetchone()
    return row[0] if row else None


def _ts(day: int, month: int, year: int = 2026) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def upgrade() -> None:
    conn = op.get_bind()

    # ── CC obs → viv_cc_pedidos ───────────────────────────────────────────────
    for row in conn.execute(sa.text(
        "SELECT id, obs FROM viv_cordon_cuneta WHERE obs IS NOT NULL AND obs != '' AND deleted_at IS NULL"
    )).fetchall():
        row_id, obs = row
        for day, month, text in _parse_obs(obs):
            try:
                fecha = date(2026, month, day)
            except ValueError:
                fecha = TODAY
            conn.execute(sa.text("""
                INSERT INTO viv_cc_pedidos (id, municipio_id, descripcion, fecha_pedido, created_at, created_by)
                VALUES (:id, :mid, :desc, :fecha, NOW(), 'importado-html')
            """), {"id": str(uuid.uuid4()), "mid": row_id, "desc": text, "fecha": fecha})

    conn.execute(sa.text("UPDATE viv_cordon_cuneta SET obs = NULL WHERE obs IS NOT NULL"))

    # ── CH obs → viv_ch_pedidos ───────────────────────────────────────────────
    for row in conn.execute(sa.text(
        "SELECT id, obs FROM viv_cordoba_hogar WHERE obs IS NOT NULL AND obs != '' AND deleted_at IS NULL"
    )).fetchall():
        row_id, obs = row
        for day, month, text in _parse_obs(obs):
            try:
                fecha = date(2026, month, day)
            except ValueError:
                fecha = TODAY
            conn.execute(sa.text("""
                INSERT INTO viv_ch_pedidos (id, localidad_id, descripcion, fecha_pedido, created_at, created_by)
                VALUES (:id, :lid, :desc, :fecha, NOW(), 'importado-html')
            """), {"id": str(uuid.uuid4()), "lid": row_id, "desc": text, "fecha": fecha})

    conn.execute(sa.text("UPDATE viv_cordoba_hogar SET obs = NULL WHERE obs IS NOT NULL"))

    # ── CC doc_exp date entries → viv_cc_estado_historial ────────────────────
    for row in conn.execute(sa.text(
        "SELECT id, doc_exp FROM viv_cordon_cuneta WHERE doc_exp IS NOT NULL AND doc_exp != '' AND deleted_at IS NULL"
    )).fetchall():
        row_id, doc_exp = row
        entries = _parse_doc_exp(doc_exp)
        for day, month, desc in entries:
            estado_nuevo_id = _find_estado_id(conn, "viv_cc_estados", desc)
            if not estado_nuevo_id:
                continue
            estado_anterior_id = _find_prev_estado_id(conn, "viv_cc_estados", estado_nuevo_id)
            campo = "etecnico" if re.search(r"\btc\b", desc.lower()) else "ejuridico"
            try:
                ts = datetime(2026, month, day, tzinfo=timezone.utc)
            except ValueError:
                ts = datetime(TODAY.year, TODAY.month, TODAY.day, tzinfo=timezone.utc)
            conn.execute(sa.text("""
                INSERT INTO viv_cc_estado_historial
                    (id, municipio_id, campo, estado_anterior_id, estado_nuevo_id, created_at, created_by)
                VALUES (:id, :mid, :campo, :ea, :en, :ts, 'importado-html')
            """), {
                "id": str(uuid.uuid4()), "mid": row_id, "campo": campo,
                "ea": estado_anterior_id, "en": estado_nuevo_id, "ts": ts,
            })
        if entries:
            cleaned = _clean_doc_exp(doc_exp)
            conn.execute(sa.text("UPDATE viv_cordon_cuneta SET doc_exp = :v WHERE id = :id"),
                         {"v": cleaned, "id": row_id})

    # ── CH doc_exp date entries → viv_ch_estado_historial ────────────────────
    for row in conn.execute(sa.text(
        "SELECT id, doc_exp FROM viv_cordoba_hogar WHERE doc_exp IS NOT NULL AND doc_exp != '' AND deleted_at IS NULL"
    )).fetchall():
        row_id, doc_exp = row
        entries = _parse_doc_exp(doc_exp)
        for day, month, desc in entries:
            estado_nuevo_id = _find_estado_id(conn, "viv_ch_estados", desc)
            if not estado_nuevo_id:
                continue
            estado_anterior_id = _find_prev_estado_id(conn, "viv_ch_estados", estado_nuevo_id)
            campo = "etecnico" if re.search(r"\btc\b", desc.lower()) else "ejuridico"
            try:
                ts = datetime(2026, month, day, tzinfo=timezone.utc)
            except ValueError:
                ts = datetime(TODAY.year, TODAY.month, TODAY.day, tzinfo=timezone.utc)
            conn.execute(sa.text("""
                INSERT INTO viv_ch_estado_historial
                    (id, localidad_id, campo, estado_anterior_id, estado_nuevo_id, created_at, created_by)
                VALUES (:id, :lid, :campo, :ea, :en, :ts::timestamptz, 'importado-html')
            """), {
                "id": str(uuid.uuid4()), "lid": row_id, "campo": campo,
                "ea": estado_anterior_id, "en": estado_nuevo_id, "ts": ts,
            })
        if entries:
            cleaned = _clean_doc_exp(doc_exp)
            conn.execute(sa.text("UPDATE viv_cordoba_hogar SET doc_exp = :v WHERE id = :id"),
                         {"v": cleaned, "id": row_id})


def downgrade() -> None:
    pass  # data migration — restore from backup if needed
