"""Estados de CC / CH / ML: un listado por área (jurídico, financiero, general)

spec-vivienda-estados-por-area.md §2-§3. Hasta ahora cada programa tenía un único
catálogo y un mismo estado podía usarse a la vez como Jurídico, Presupuestario y
General (flags `aplica_*`). Desde esta migración cada estado pertenece a un solo
listado (`dimension`).

Para cada estado se calcula en qué listados va: Jurídico y Presupuestario si tiene
el flag o alguna entidad / entrada de historial lo usa ahí; General siempre (antes el
Estado General podía elegir cualquier estado del catálogo), salvo los estados que solo
se usaban como Técnico, que quedan en `tecnico_anterior`. Si va a un solo listado, se
le asigna esa `dimension` y conserva su id. Si va a varios, el primero (jurídico, financiero, general)
conserva el id y para cada otro se inserta una copia con id nuevo; las columnas de
la entidad y las entradas de historial de ese listado se repuntan a la copia.

Los flags `aplica_*` y la columna `etecnico` quedan congelados: no se tocan.
Cada copia y cada repunte deja una fila en `viv_audit_log`; de ahí sale el downgrade.

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-21
"""
import json
import time
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

_ACTOR = "migracion-0044-estados-por-area"

# (catálogo, entidad, historial, prefijo del audit log)
_PROGRAMAS = [
    ("viv_cc_estados", "viv_cordon_cuneta", "viv_cc_estado_historial", "cc"),
    ("viv_ch_estados", "viv_cordoba_hogar", "viv_ch_estado_historial", "ch"),
    ("viv_ml_estados", "viv_ml_proyectos", "viv_ml_estado_historial", "ml"),
]

_DIMENSIONES = ("juridico", "financiero", "general", "tecnico_anterior")

# dimension → (flag del catálogo, columna de la entidad, `campo` del historial)
_USOS = {
    "juridico": ("aplica_juridico", "ejuridico", "ejuridico"),
    "financiero": ("aplica_financiero", "efinanciero", "efinanciero"),
    "general": (None, "estado_general", None),
}


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


def _ids(conn, sql: str) -> set[int]:
    return {r[0] for r in conn.execute(sa.text(sql)).fetchall() if r[0] is not None}


def _migrar_programa(conn, now, catalogo, entidad, historial, prefijo, proximo_id) -> int:
    estados = conn.execute(sa.text(
        f"SELECT id, aplica_juridico, aplica_tecnico, aplica_financiero FROM {catalogo} ORDER BY orden, id"
    )).mappings().fetchall()

    usados: dict[str, set[int]] = {}
    for dim, (_, col, campo) in _USOS.items():
        ids = _ids(conn, f"SELECT DISTINCT {col} FROM {entidad}")
        if campo:
            ids |= _ids(conn, f"SELECT DISTINCT estado_nuevo_id FROM {historial} WHERE campo = '{campo}'")
            ids |= _ids(conn, f"SELECT DISTINCT estado_anterior_id FROM {historial} WHERE campo = '{campo}'")
        usados[dim] = ids
    tecnicos = _ids(conn, f"SELECT DISTINCT etecnico FROM {entidad}")
    tecnicos |= _ids(conn, f"SELECT DISTINCT estado_nuevo_id FROM {historial} WHERE campo = 'etecnico'")
    tecnicos |= _ids(conn, f"SELECT DISTINCT estado_anterior_id FROM {historial} WHERE campo = 'etecnico'")

    resumen = {"estados": len(estados), "duplicados": 0, "filas_repuntadas": 0, "historial_repuntado": 0}
    for e in estados:
        dims = [
            dim for dim in ("juridico", "financiero")
            if e[_USOS[dim][0]] or e["id"] in usados[dim]
        ]
        solo_tecnico = not dims and e["id"] not in usados["general"] and (e["aplica_tecnico"] or e["id"] in tecnicos)
        # Antes el Estado General podía tomar cualquier estado del catálogo: el listado General
        # arranca con todos, para que nadie pierda una opción el día del cambio.
        dims = ["tecnico_anterior"] if solo_tecnico else dims + ["general"]

        conn.execute(sa.text(f"UPDATE {catalogo} SET dimension = :dim WHERE id = :id"), {"dim": dims[0], "id": e["id"]})

        for dim in dims[1:]:
            nuevo = proximo_id
            proximo_id += 1
            lista = ", ".join(c for c in _columnas(conn, catalogo) if c not in ("id", "dimension"))
            conn.execute(
                sa.text(
                    f"INSERT INTO {catalogo} (id, dimension, {lista}) "
                    f"SELECT :nuevo, :dim, {lista} FROM {catalogo} WHERE id = :id"
                ),
                {"nuevo": nuevo, "dim": dim, "id": e["id"]},
            )
            _, col, campo = _USOS[dim]
            filas = [r[0] for r in conn.execute(
                sa.text(f"SELECT id FROM {entidad} WHERE {col} = :id"), {"id": e["id"]}
            ).fetchall()]
            if filas:
                conn.execute(
                    sa.text(f"UPDATE {entidad} SET {col} = :nuevo WHERE {col} = :id"),
                    {"nuevo": nuevo, "id": e["id"]},
                )
            hist_ant = hist_nue = []
            if campo:
                hist_nue = [r[0] for r in conn.execute(sa.text(
                    f"SELECT id FROM {historial} WHERE campo = :campo AND estado_nuevo_id = :id"
                ), {"campo": campo, "id": e["id"]}).fetchall()]
                hist_ant = [r[0] for r in conn.execute(sa.text(
                    f"SELECT id FROM {historial} WHERE campo = :campo AND estado_anterior_id = :id"
                ), {"campo": campo, "id": e["id"]}).fetchall()]
                conn.execute(sa.text(
                    f"UPDATE {historial} SET estado_nuevo_id = :nuevo WHERE campo = :campo AND estado_nuevo_id = :id"
                ), {"nuevo": nuevo, "campo": campo, "id": e["id"]})
                conn.execute(sa.text(
                    f"UPDATE {historial} SET estado_anterior_id = :nuevo WHERE campo = :campo AND estado_anterior_id = :id"
                ), {"nuevo": nuevo, "campo": campo, "id": e["id"]})
            _audit(conn, now, f"{prefijo}_estado", str(nuevo), {
                "motivo": "copia por listado (migración 0044)",
                "original": e["id"], "dimension": dim, "columna": col,
                "filas": [str(f) for f in filas],
                "historial_nuevo": [str(h) for h in hist_nue],
                "historial_anterior": [str(h) for h in hist_ant],
            })
            resumen["duplicados"] += 1
            resumen["filas_repuntadas"] += len(filas)
            resumen["historial_repuntado"] += len(hist_nue) + len(hist_ant)

    print(f"[0044] {catalogo}: {resumen}")
    return proximo_id


def _columnas(conn, tabla: str) -> list[str]:
    return [c["name"] for c in sa.inspect(conn).get_columns(tabla)]


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    checks = ", ".join(f"'{d}'" for d in _DIMENSIONES)
    for catalogo, *_ in _PROGRAMAS:
        op.add_column(catalogo, sa.Column("dimension", sa.String(16), nullable=False, server_default="general"))
        op.create_check_constraint(f"ck_{catalogo}_dimension", catalogo, f"dimension IN ({checks})")

    # Ids nuevos por encima de todo lo existente y del reloj (los estados nuevos usan epoch en ms).
    maximo = max(
        [conn.execute(sa.text(f"SELECT COALESCE(MAX(id), 0) FROM {c}")).scalar_one() for c, *_ in _PROGRAMAS]
        + [int(time.time() * 1000)]
    )
    proximo_id = maximo + 1
    for catalogo, entidad, historial, prefijo in _PROGRAMAS:
        proximo_id = _migrar_programa(conn, now, catalogo, entidad, historial, prefijo, proximo_id)


def downgrade() -> None:
    conn = op.get_bind()
    por_prefijo = {prefijo: (catalogo, entidad, historial) for catalogo, entidad, historial, prefijo in _PROGRAMAS}
    filas = conn.execute(
        sa.text("SELECT resource_type, resource_id, payload FROM viv_audit_log WHERE actor_uid = :actor"),
        {"actor": _ACTOR},
    ).fetchall()
    for resource_type, resource_id, payload in filas:
        catalogo, entidad, historial = por_prefijo[resource_type.removesuffix("_estado")]
        datos = json.loads(payload)
        copia, original = int(resource_id), datos["original"]
        conn.execute(
            sa.text(f"UPDATE {entidad} SET {datos['columna']} = :original WHERE {datos['columna']} = :copia"),
            {"original": original, "copia": copia},
        )
        conn.execute(sa.text(f"UPDATE {historial} SET estado_nuevo_id = :original WHERE estado_nuevo_id = :copia"),
                     {"original": original, "copia": copia})
        conn.execute(sa.text(f"UPDATE {historial} SET estado_anterior_id = :original WHERE estado_anterior_id = :copia"),
                     {"original": original, "copia": copia})
        conn.execute(sa.text(f"DELETE FROM {catalogo} WHERE id = :copia"), {"copia": copia})
    conn.execute(sa.text("DELETE FROM viv_audit_log WHERE actor_uid = :actor"), {"actor": _ACTOR})
    for catalogo, *_ in _PROGRAMAS:
        op.drop_constraint(f"ck_{catalogo}_dimension", catalogo, type_="check")
        op.drop_column(catalogo, "dimension")
