"""Córdoba Hogar: Convenio Firmado como dato propio de la localidad

spec-ch-convenio-firmado.md §2 y §5. Agrega `convenio_firmado` + `fecha_firma_convenio` y marca
las localidades activas que están o estuvieron en "Convenio Firmado" del listado Jurídico.

La fecha es la de la primera entrada de historial que llega al estado. Queda NULL si no hay
entrada de llegada (ya estaban firmadas al empezar el historial) o si esa entrada es de la
importación inicial, porque su fecha es la de la importación y no la de la firma.

Cada localidad marcada deja una fila en `viv_audit_log`; el downgrade borra esas filas.

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-02
"""
import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

_ACTOR = "migracion-0046-ch-convenio-firmado"
_IMPORTACION = "importado-html"


def upgrade() -> None:
    op.add_column(
        "viv_cordoba_hogar",
        sa.Column("convenio_firmado", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("viv_cordoba_hogar", sa.Column("fecha_firma_convenio", sa.Date(), nullable=True))

    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    estados = {r[0] for r in conn.execute(sa.text(
        "SELECT id FROM viv_ch_estados "
        "WHERE dimension = 'juridico' AND lower(trim(label)) = 'convenio firmado'"
    )).fetchall()}
    if not estados:
        print("[0046] sin estado 'Convenio Firmado' en el listado Jurídico: no se marca ninguna localidad")
        return

    marcadas = {
        r[0]: None
        for r in conn.execute(sa.text(
            "SELECT id, ejuridico FROM viv_cordoba_hogar WHERE deleted_at IS NULL"
        )).fetchall()
        if r[1] in estados
    }
    activas = {r[0] for r in conn.execute(sa.text(
        "SELECT id FROM viv_cordoba_hogar WHERE deleted_at IS NULL"
    )).fetchall()}
    # Orden cronológico: la primera llegada de cada localidad define la fecha.
    historial = conn.execute(sa.text(
        "SELECT localidad_id, estado_anterior_id, estado_nuevo_id, created_at, created_by "
        "FROM viv_ch_estado_historial WHERE campo = 'ejuridico' ORDER BY created_at"
    )).fetchall()
    con_llegada: set[str] = set()
    for localidad_id, anterior, nuevo, creado, autor in historial:
        if localidad_id not in activas:
            continue
        if anterior in estados:
            marcadas.setdefault(localidad_id, None)
        if nuevo in estados:
            marcadas.setdefault(localidad_id, None)
            if localidad_id not in con_llegada:
                con_llegada.add(localidad_id)
                if autor != _IMPORTACION:
                    # SQLite/psycopg pueden devolver texto o datetime según el driver.
                    marcadas[localidad_id] = (
                        creado.date() if hasattr(creado, "date") else datetime.fromisoformat(str(creado)).date()
                    )

    for localidad_id, fecha in marcadas.items():
        conn.execute(
            sa.text(
                "UPDATE viv_cordoba_hogar SET convenio_firmado = :firmado, fecha_firma_convenio = :fecha "
                "WHERE id = :id"
            ),
            {"firmado": True, "fecha": fecha, "id": localidad_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO viv_audit_log "
                "(id, actor_uid, actor_email, actor_role, action, resource_type, resource_id, payload, created_at) "
                "VALUES (:id, :actor, :actor, 'system', 'UPDATE', 'cordoba_hogar', :resource_id, :payload, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "actor": _ACTOR,
                "resource_id": localidad_id,
                "payload": json.dumps({
                    "convenio_firmado": True,
                    "fecha_firma_convenio": fecha.isoformat() if fecha else None,
                }),
                "created_at": now,
            },
        )
    con_fecha = sum(1 for f in marcadas.values() if f)
    print(f"[0046] localidades marcadas: {len(marcadas)} de {len(activas)} activas; con fecha: {con_fecha}")


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM viv_audit_log WHERE actor_uid = :actor"), {"actor": _ACTOR}
    )
    op.drop_column("viv_cordoba_hogar", "fecha_firma_convenio")
    op.drop_column("viv_cordoba_hogar", "convenio_firmado")
