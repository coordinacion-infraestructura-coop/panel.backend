"""Censo: repunta id_geo donde difiere del nomenclador de Gobierno

La carga del Censo 2022 (0002) vinculó por nombre, porque el Cuadro 1.6 no
trae departamento. El nomenclador de Gobierno (0003) vincula el mismo código
INDEC por nombre **y** departamento, así que donde los dos difieren manda el
nomenclador. Caso real (2026-10-19): el código 142672, comuna "Kilómetro 658"
(Río Primero), estaba vinculado a la fila del padrón "KILOMETRO 691", un
paraje que según Georef no es ningún gobierno local. Tras el alta de
Kilómetro 658 en el padrón (svc-vivienda 0042) el rollup la mostraba dos
veces: la población en un `id_geo` y la ficha de Gobierno en el otro.

Solo toca filas donde el nomenclador tiene `id_geo` y ninguna otra fila del
Censo lo usa. Lo que cambia queda en `ext_gob_sync_log` (fuente
`migracion_0004`); de ahí sale el downgrade.

Spec: spec-datos-externos-fase1-nomenclador-demografia.md §5.1.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""
import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_FUENTE = "migracion_0004"


def upgrade() -> None:
    conn = op.get_bind()
    filas = conn.execute(sa.text(
        "SELECT c.id, c.codigo_indec, c.id_geo, c.match_tipo, c.departamento_censo, g.id_geo, g.departamento_gob "
        "FROM ext_geo_censo c JOIN ext_gob_localidades g ON g.codigo_indec = c.codigo_indec "
        "WHERE c.deleted_at IS NULL AND g.deleted_at IS NULL AND g.id_geo IS NOT NULL "
        "AND c.id_geo IS NOT NULL AND c.id_geo <> g.id_geo"
    )).fetchall()
    en_uso = {r[0] for r in conn.execute(sa.text(
        "SELECT id_geo FROM ext_geo_censo WHERE deleted_at IS NULL AND id_geo IS NOT NULL"
    )).fetchall()}
    cambios = []
    for censo_id, codigo, id_geo, match_tipo, depto, id_geo_nom, depto_nom in filas:
        if id_geo_nom in en_uso:
            continue
        conn.execute(
            sa.text(
                "UPDATE ext_geo_censo SET id_geo = :id_geo, match_tipo = 'nomenclador_gob', "
                "departamento_censo = :depto WHERE id = :id"
            ),
            {"id_geo": id_geo_nom, "depto": depto_nom, "id": censo_id},
        )
        en_uso.discard(id_geo)
        en_uso.add(id_geo_nom)
        cambios.append({"id": censo_id, "codigo": codigo,
                        "antes": {"id_geo": id_geo, "match_tipo": match_tipo, "departamento_censo": depto},
                        "despues": {"id_geo": id_geo_nom}})
    conn.execute(
        sa.text(
            "INSERT INTO ext_gob_sync_log (id, fuente, filas_leidas, filas_upsert, filas_error, filas_sin_match, "
            "anomalias, estado, corrida_en, disparado_por) "
            "VALUES (:id, :fuente, :leidas, :upsert, 0, 0, :anomalias, 'ok', :ahora, 'alembic')"
        ),
        {"id": str(uuid.uuid4()), "fuente": _FUENTE, "leidas": len(filas), "upsert": len(cambios),
         "anomalias": json.dumps(cambios), "ahora": datetime.now(timezone.utc)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    for (anomalias,) in conn.execute(
        sa.text("SELECT anomalias FROM ext_gob_sync_log WHERE fuente = :f"), {"f": _FUENTE}
    ).fetchall():
        cambios = anomalias if isinstance(anomalias, list) else json.loads(anomalias or "[]")
        for c in cambios:
            conn.execute(
                sa.text(
                    "UPDATE ext_geo_censo SET id_geo = :id_geo, match_tipo = :match, "
                    "departamento_censo = :depto WHERE id = :id"
                ),
                {"id_geo": c["antes"]["id_geo"], "match": c["antes"]["match_tipo"],
                 "depto": c["antes"]["departamento_censo"], "id": c["id"]},
            )
    conn.execute(sa.text("DELETE FROM ext_gob_sync_log WHERE fuente = :f"), {"f": _FUENTE})
