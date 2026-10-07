"""CC / CH / Mi Lugar: el nombre guardado pasa a ser el del padrón oficial

Decisión del usuario 2026-10-07 (ADR-026): todo por detrás usa el padrón
oficial de localidades. Cambia spec-normalizacion-localidades.md §2.6, que
hasta ahora decía que el texto de cada registro no se pisaba.

Para cada registro activo de `viv_cordon_cuneta`, `viv_cordoba_hogar` y
`viv_ml_proyectos` **con vínculo** (`localidad_id` no nulo), el nombre de
localidad y el departamento pasan a ser los de su fila del padrón. Los
registros sin vínculo (loteos de Mi Lugar por barrio de Capital) no se tocan.

Medido en producción el mismo día: 36 nombres (31 sólo por mayúsculas/tildes;
los otros son "CHARRAS" ×2 → "CHARRAS (VILLA COLON)", "LUXARDO" → "PLAZA
LUXARDO", "GENERAL BALDISERA" → "GENERAL BALDISSERA") y 3 departamentos.

Cada registro modificado deja una fila en `viv_audit_log` con el valor
anterior — de ahí sale el downgrade.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-07
"""
import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_ACTOR = "migracion-0037-nombre-oficial"

# (tabla, columna del nombre, resource_type del audit log)
_TABLAS = [
    ("viv_cordon_cuneta", "municipio", "cordon_cuneta"),
    ("viv_cordoba_hogar", "localidad", "cordoba_hogar"),
    ("viv_ml_proyectos", "localidad_nombre", "mi_lugar"),
]


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    for tabla, col, resource_type in _TABLAS:
        filas = conn.execute(sa.text(
            f"SELECT t.id, t.{col}, t.departamento, g.localidad, g.departamento "
            f"FROM {tabla} t JOIN viv_geo_localidades g ON g.id_geo = t.localidad_id "
            f"WHERE t.deleted_at IS NULL"
        )).fetchall()
        for row_id, nombre, departamento, nombre_oficial, departamento_oficial in filas:
            if nombre == nombre_oficial and departamento == departamento_oficial:
                continue
            conn.execute(
                sa.text(f"UPDATE {tabla} SET {col} = :nombre, departamento = :departamento WHERE id = :id"),
                {"nombre": nombre_oficial, "departamento": departamento_oficial, "id": row_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO viv_audit_log "
                    "(id, actor_uid, actor_email, actor_role, action, resource_type, resource_id, payload, created_at) "
                    "VALUES (:id, :actor, :actor, 'system', 'UPDATE', :resource_type, :resource_id, :payload, :created_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "actor": _ACTOR,
                    "resource_type": resource_type,
                    "resource_id": row_id,
                    "payload": json.dumps({
                        "motivo": "nombre oficial del padrón (ADR-026)",
                        "antes": {col: nombre, "departamento": departamento},
                        "despues": {col: nombre_oficial, "departamento": departamento_oficial},
                    }, ensure_ascii=False),
                    "created_at": now,
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    por_tipo = {resource_type: (tabla, col) for tabla, col, resource_type in _TABLAS}
    for resource_type, resource_id, payload in conn.execute(
        sa.text("SELECT resource_type, resource_id, payload FROM viv_audit_log WHERE actor_uid = :actor"),
        {"actor": _ACTOR},
    ).fetchall():
        tabla, col = por_tipo[resource_type]
        antes = json.loads(payload)["antes"]
        conn.execute(
            sa.text(f"UPDATE {tabla} SET {col} = :nombre, departamento = :departamento WHERE id = :id"),
            {"nombre": antes[col], "departamento": antes["departamento"], "id": resource_id},
        )
    conn.execute(sa.text("DELETE FROM viv_audit_log WHERE actor_uid = :actor"), {"actor": _ACTOR})
