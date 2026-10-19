"""Padrón: alta de Santiago Temple y Kilómetro 658

Las dos estaban registradas como "confirmado sin vínculo" (alias con
`id_geo = NULL`: Santiago Temple desde el seed original de ATP, Kilómetro 658
desde las migraciones 0032/0034) porque no figuraban en el padrón y la regla
es no inventar un `id_geo`. El nomenclador INDEC de Gobierno
(spec-datos-externos-fase1-nomenclador-demografia.md) y la API Georef
(apis.datos.gob.ar, consultada el 2026-10-19) confirman que son gobiernos
locales reales:

| Localidad      | Departamento | Gob. local INDEC | Tipo      | Localidad Georef |
|----------------|--------------|------------------|-----------|------------------|
| SANTIAGO TEMPLE| RÍO SEGUNDO  | 141078           | Municipio | 14119200         |
| KILÓMETRO 658  | RÍO PRIMERO  | 142672           | Comuna    | 14105100         |

El alta de una localidad que falta va por migración
(spec-geo-asignacion-manual-localidades.md §2). Decisión del usuario
2026-10-19.

Esta migración:
1. Inserta las dos filas en `viv_geo_localidades` con el siguiente `id_geo`
   numérico libre y el centroide de la localidad según Georef.
2. Repunta los alias "confirmado sin vínculo" de esos nombres a la fila nueva:
   desde la próxima corrida, ATP, Gasífera, Privada y Datos Externos las
   resuelven solas.
3. Vincula los registros activos de CC/CH/ML sin `localidad_id` que tengan
   esos nombres (nombre y departamento oficiales, ADR-026).

Cada cambio deja una fila en `viv_audit_log`; de ahí sale el downgrade.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-19
"""
import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.geo.matching import normalize_departamento, normalize_name

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

_ACTOR = "migracion-0042-alta-padron"

# (localidad, departamento, lat, lon) — centroide de la localidad según Georef.
_ALTAS = [
    ("SANTIAGO TEMPLE", "RÍO SEGUNDO", -31.3859854, -63.4196375),
    ("KILÓMETRO 658", "RÍO PRIMERO", -31.3688486, -63.5306284),
]

# (tabla, columna del nombre, resource_type del audit log)
_TABLAS = [
    ("viv_cordon_cuneta", "municipio", "cordon_cuneta"),
    ("viv_cordoba_hogar", "localidad", "cordoba_hogar"),
    ("viv_ml_proyectos", "localidad_nombre", "mi_lugar"),
]


def _audit(conn, now, resource_type: str, resource_id: str, payload: dict) -> None:
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
            "resource_id": resource_id,
            "payload": json.dumps(payload, ensure_ascii=False),
            "created_at": now,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    padron = conn.execute(sa.text("SELECT id_geo, departamento, localidad FROM viv_geo_localidades")).fetchall()
    existentes = {(normalize_name(loc), normalize_departamento(dep)): id_geo for id_geo, dep, loc in padron}
    siguiente = max((int(r[0]) for r in padron if str(r[0]).isdigit()), default=0) + 1

    for localidad, departamento, lat, lon in _ALTAS:
        clave = (normalize_name(localidad), normalize_departamento(departamento))
        id_geo = existentes.get(clave)
        if id_geo is None:
            id_geo = str(siguiente)
            siguiente += 1
            conn.execute(
                sa.text(
                    "INSERT INTO viv_geo_localidades (id_geo, departamento, localidad, lat_centro, lon_centro, activo) "
                    "VALUES (:id_geo, :departamento, :localidad, :lat, :lon, true)"
                ),
                {"id_geo": id_geo, "departamento": departamento, "localidad": localidad, "lat": lat, "lon": lon},
            )
            _audit(conn, now, "geo_localidad", id_geo, {"motivo": "alta en el padrón", "localidad": localidad})

        # Alias "confirmado sin vínculo" de ese nombre → la fila nueva.
        for alias_id, motivo in conn.execute(
            sa.text(
                "SELECT id, motivo FROM viv_geo_alias_manual "
                "WHERE texto_normalizado = :texto AND id_geo IS NULL AND deleted_at IS NULL"
            ),
            {"texto": clave[0]},
        ).fetchall():
            nuevo_motivo = f"alta en el padrón (migración 0042, INDEC); antes: {motivo or 'sin vínculo'}"
            conn.execute(
                sa.text(
                    "UPDATE viv_geo_alias_manual SET id_geo = :id_geo, motivo = :motivo, "
                    "updated_at = :now, updated_by = :actor WHERE id = :id"
                ),
                {"id_geo": id_geo, "motivo": nuevo_motivo, "now": now, "actor": _ACTOR, "id": alias_id},
            )
            _audit(conn, now, "geo_alias", alias_id, {"antes": {"id_geo": None, "motivo": motivo}, "despues": {"id_geo": id_geo}})

        # Registros de CC/CH/ML sin vínculo con ese nombre (y, si lo tienen, ese departamento).
        for tabla, col, resource_type in _TABLAS:
            for row_id, nombre, dep_actual, match_actual in conn.execute(sa.text(
                f"SELECT id, {col}, departamento, localidad_match_tipo FROM {tabla} "
                f"WHERE deleted_at IS NULL AND localidad_id IS NULL"
            )).fetchall():
                if normalize_name(nombre) != clave[0]:
                    continue
                if dep_actual and normalize_departamento(dep_actual) != clave[1]:
                    continue
                conn.execute(
                    sa.text(
                        f"UPDATE {tabla} SET localidad_id = :id_geo, localidad_match_tipo = 'manual', "
                        f"{col} = :nombre, departamento = :departamento WHERE id = :id"
                    ),
                    {"id_geo": id_geo, "nombre": localidad, "departamento": departamento, "id": row_id},
                )
                _audit(conn, now, resource_type, row_id, {
                    "motivo": "vínculo al alta en el padrón (migración 0042)",
                    "antes": {col: nombre, "departamento": dep_actual, "localidad_id": None,
                              "localidad_match_tipo": match_actual},
                })


def downgrade() -> None:
    conn = op.get_bind()
    por_tipo = {resource_type: (tabla, col) for tabla, col, resource_type in _TABLAS}
    filas = conn.execute(
        sa.text("SELECT resource_type, resource_id, payload FROM viv_audit_log WHERE actor_uid = :actor"),
        {"actor": _ACTOR},
    ).fetchall()
    altas = []
    for resource_type, resource_id, payload in filas:
        datos = json.loads(payload)
        if resource_type in por_tipo:
            tabla, col = por_tipo[resource_type]
            antes = datos["antes"]
            conn.execute(
                sa.text(
                    f"UPDATE {tabla} SET localidad_id = NULL, localidad_match_tipo = :match, "
                    f"{col} = :nombre, departamento = :departamento WHERE id = :id"
                ),
                {"match": antes["localidad_match_tipo"], "nombre": antes[col],
                 "departamento": antes["departamento"], "id": resource_id},
            )
        elif resource_type == "geo_alias":
            conn.execute(
                sa.text("UPDATE viv_geo_alias_manual SET id_geo = NULL, motivo = :motivo WHERE id = :id"),
                {"motivo": datos["antes"]["motivo"], "id": resource_id},
            )
        elif resource_type == "geo_localidad":
            altas.append(resource_id)
    for id_geo in altas:
        conn.execute(sa.text("DELETE FROM viv_geo_localidades WHERE id_geo = :id"), {"id": id_geo})
    conn.execute(sa.text("DELETE FROM viv_audit_log WHERE actor_uid = :actor"), {"actor": _ACTOR})
