"""Portal: áreas de acceso por secretaría (y fin del rol TecnicoDGV)

spec-portal-areas-de-acceso.md §4 y §7. Crea `portal_usuario_areas` y la completa
para que nadie cambie de acceso el día del deploy:

- usuario con la secretaría `vivienda`: todas sus áreas (cc, ch, ml, checklist),
  en `edicion` si el rol es Admin / Supervisor / Operador y en `lectura` si es
  Consulta / Autoridad;
- `TecnicoDGV` pasa a `Operador` con solo `checklist` en `edicion` (se le asigna
  `vivienda` si no la tenía).

Imprime la lista de usuarios que hoy podían leer los paneles de Vivienda sin tener
la secretaría asignada (el hueco que cierra el spec, §1): revisarla antes de desplegar.
Cada cambio de rol o de secretaría deja fila en `viv_audit_log`; de ahí sale el downgrade.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-21
"""
import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

_ACTOR = "migracion-0045-areas-de-acceso"
_AREAS_VIVIENDA = ("cc", "ch", "ml", "checklist")
_ROLES_EDICION = ("Admin", "Supervisor", "Operador")
_ROLES_LECTURA_PANELES = ("Supervisor", "Operador", "Consulta", "Autoridad")
_SECRETARIAS_COMUNICACIONES = ("infraestructura", "supervision")


def _audit(conn, now, resource_id: str, payload: dict) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO viv_audit_log "
            "(id, actor_uid, actor_email, actor_role, action, resource_type, resource_id, payload, created_at) "
            "VALUES (:id, :actor, :actor, 'system', 'UPDATE', 'portal_usuario', :resource_id, :payload, :created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "actor": _ACTOR,
            "resource_id": resource_id[:36],
            "payload": json.dumps(payload, ensure_ascii=False),
            "created_at": now,
        },
    )


def upgrade() -> None:
    op.create_table(
        "portal_usuario_areas",
        sa.Column("email", sa.String(255), sa.ForeignKey("portal_usuarios.email", ondelete="CASCADE"), primary_key=True),
        sa.Column("secretaria", sa.String(100), primary_key=True),
        sa.Column("area", sa.String(50), primary_key=True),
        sa.Column("nivel", sa.String(10), nullable=False),
        sa.CheckConstraint("nivel IN ('lectura', 'edicion')", name="ck_portal_usuario_areas_nivel"),
    )

    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    secretarias: dict[str, set[str]] = {}
    for email, sec in conn.execute(sa.text("SELECT email, secretaria FROM portal_usuario_secretarias")).fetchall():
        secretarias.setdefault(email, set()).add(sec)

    sin_vivienda = []
    insertar = sa.text(
        "INSERT INTO portal_usuario_areas (email, secretaria, area, nivel) VALUES (:email, 'vivienda', :area, :nivel)"
    )
    for email, rol in conn.execute(sa.text("SELECT email, rol FROM portal_usuarios ORDER BY email")).fetchall():
        propias = secretarias.get(email, set())
        if rol == "TecnicoDGV":
            conn.execute(sa.text("UPDATE portal_usuarios SET rol = 'Operador' WHERE email = :email"), {"email": email})
            agrego_vivienda = "vivienda" not in propias
            if agrego_vivienda:
                conn.execute(
                    sa.text("INSERT INTO portal_usuario_secretarias (email, secretaria) VALUES (:email, 'vivienda')"),
                    {"email": email},
                )
            conn.execute(insertar, {"email": email, "area": "checklist", "nivel": "edicion"})
            _audit(conn, now, email, {
                "email": email, "motivo": "TecnicoDGV → Operador + área checklist (migración 0045)",
                "rol_anterior": "TecnicoDGV", "agrego_vivienda": agrego_vivienda,
            })
            continue
        if "vivienda" in propias:
            nivel = "edicion" if rol in _ROLES_EDICION else "lectura"
            for area in _AREAS_VIVIENDA:
                conn.execute(insertar, {"email": email, "area": area, "nivel": nivel})
        elif rol in _ROLES_LECTURA_PANELES and not propias & set(_SECRETARIAS_COMUNICACIONES):
            sin_vivienda.append(f"{email} ({rol}; {', '.join(sorted(propias)) or 'sin secretarías'})")

    print(f"[0045] usuarios que dejan de poder leer los paneles de Vivienda: {len(sin_vivienda)}")
    for linea in sin_vivienda:
        print(f"[0045]   {linea}")


def downgrade() -> None:
    conn = op.get_bind()
    for (payload,) in conn.execute(
        sa.text("SELECT payload FROM viv_audit_log WHERE actor_uid = :actor"), {"actor": _ACTOR}
    ).fetchall():
        datos = json.loads(payload)
        conn.execute(
            sa.text("UPDATE portal_usuarios SET rol = :rol WHERE email = :email"),
            {"rol": datos["rol_anterior"], "email": datos["email"]},
        )
        if datos["agrego_vivienda"]:
            conn.execute(
                sa.text("DELETE FROM portal_usuario_secretarias WHERE email = :email AND secretaria = 'vivienda'"),
                {"email": datos["email"]},
            )
    conn.execute(sa.text("DELETE FROM viv_audit_log WHERE actor_uid = :actor"), {"actor": _ACTOR})
    op.drop_table("portal_usuario_areas")
