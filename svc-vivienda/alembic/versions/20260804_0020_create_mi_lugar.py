"""create mi_lugar module

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-04
"""
from __future__ import annotations

import uuid
from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── viv_ml_estados ────────────────────────────────────────────────────────
    op.create_table(
        "viv_ml_estados",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("bg", sa.String(10), nullable=False),
        sa.Column("text_color", sa.String(10), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("aplica_juridico", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("aplica_tecnico", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("aplica_financiero", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── viv_ml_proyectos ──────────────────────────────────────────────────────
    op.create_table(
        "viv_ml_proyectos",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("localidad_id", sa.String(36), nullable=True),
        sa.Column("localidad_nombre", sa.String(150), nullable=False),
        sa.Column("departamento", sa.String(100), nullable=True),
        sa.Column("expediente", sa.String(80), nullable=True),
        sa.Column("responsable", sa.String(150), nullable=True),
        sa.Column("superficie", sa.Numeric(10, 4), nullable=True),
        sa.Column("lotes", sa.Integer(), nullable=True),
        sa.Column("monto", sa.Numeric(18, 2), nullable=True),
        sa.Column("valor_fiscal", sa.Numeric(18, 2), nullable=True),
        sa.Column("infra_sin_nexos", sa.Numeric(18, 2), nullable=True),
        sa.Column("costo_nexos", sa.Numeric(18, 2), nullable=True),
        sa.Column("convenio_unc", sa.Numeric(18, 2), nullable=True),
        sa.Column("costo_total_infra", sa.Numeric(18, 2), nullable=True),
        sa.Column("ok_gob", sa.String(20), server_default="SI", nullable=False),
        sa.Column("ejuridico", sa.BigInteger(), nullable=True),
        sa.Column("etecnico", sa.BigInteger(), nullable=True),
        sa.Column("efinanciero", sa.BigInteger(), nullable=True),
        sa.Column("estado_general", sa.BigInteger(), nullable=True),
        sa.Column("obs", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["localidad_id"], ["viv_geo_localidades.id"]),
        sa.ForeignKeyConstraint(["ejuridico"], ["viv_ml_estados.id"]),
        sa.ForeignKeyConstraint(["etecnico"], ["viv_ml_estados.id"]),
        sa.ForeignKeyConstraint(["efinanciero"], ["viv_ml_estados.id"]),
        sa.ForeignKeyConstraint(["estado_general"], ["viv_ml_estados.id"], name="fk_ml_estado_general"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_viv_ml_proyectos_tipo", "viv_ml_proyectos", ["tipo"])
    op.create_index("ix_viv_ml_proyectos_deleted_at", "viv_ml_proyectos", ["deleted_at"])

    # ── viv_ml_geo_puntos ─────────────────────────────────────────────────────
    op.create_table(
        "viv_ml_geo_puntos",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("proyecto_id", sa.String(36), nullable=False),
        sa.Column("lat", sa.Numeric(10, 7), nullable=False),
        sa.Column("lng", sa.Numeric(10, 7), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["proyecto_id"], ["viv_ml_proyectos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_viv_ml_geo_puntos_proyecto_id", "viv_ml_geo_puntos", ["proyecto_id"])

    # ── viv_ml_estado_historial ───────────────────────────────────────────────
    op.create_table(
        "viv_ml_estado_historial",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("proyecto_id", sa.String(36), nullable=False),
        sa.Column("campo", sa.String(30), nullable=False),
        sa.Column("estado_anterior_id", sa.BigInteger(), nullable=True),
        sa.Column("estado_nuevo_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["proyecto_id"], ["viv_ml_proyectos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["estado_anterior_id"], ["viv_ml_estados.id"]),
        sa.ForeignKeyConstraint(["estado_nuevo_id"], ["viv_ml_estados.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_viv_ml_historial_proyecto_id", "viv_ml_estado_historial", ["proyecto_id"])

    # ── viv_ml_pedidos ────────────────────────────────────────────────────────
    op.create_table(
        "viv_ml_pedidos",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("proyecto_id", sa.String(36), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("fecha_pedido", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_by_nombre", sa.String(255), nullable=True),
        sa.Column("secretaria", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(["proyecto_id"], ["viv_ml_proyectos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_viv_ml_pedidos_proyecto_id", "viv_ml_pedidos", ["proyecto_id"])

    # ── viv_ml_config ─────────────────────────────────────────────────────────
    op.create_table(
        "viv_ml_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(12, 2), server_default="1450", nullable=False),
        sa.Column("usd_por_lote", sa.Numeric(12, 2), server_default="10000", nullable=False),
        sa.Column("lotes_por_ha", sa.Numeric(8, 4), server_default="25", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Seed: estados ─────────────────────────────────────────────────────────
    from app.mi_lugar.seed_data import CONFIG_SEED, ESTADOS_SEED, PROYECTOS_SEED

    estados_tbl = sa.table(
        "viv_ml_estados",
        sa.column("id", sa.BigInteger()),
        sa.column("label", sa.String()),
        sa.column("bg", sa.String()),
        sa.column("text_color", sa.String()),
        sa.column("orden", sa.Integer()),
        sa.column("aplica_juridico", sa.Boolean()),
        sa.column("aplica_tecnico", sa.Boolean()),
        sa.column("aplica_financiero", sa.Boolean()),
    )
    op.bulk_insert(estados_tbl, [
        {**e, "aplica_juridico": True, "aplica_tecnico": True, "aplica_financiero": True}
        for e in ESTADOS_SEED
    ])

    # ── Seed: config ──────────────────────────────────────────────────────────
    config_tbl = sa.table(
        "viv_ml_config",
        sa.column("id", sa.Integer()),
        sa.column("tipo_cambio", sa.Numeric()),
        sa.column("usd_por_lote", sa.Numeric()),
        sa.column("lotes_por_ha", sa.Numeric()),
    )
    op.bulk_insert(config_tbl, [{"id": 1, **CONFIG_SEED}])

    # ── Seed: 49 proyectos + geo_puntos ───────────────────────────────────────
    proyectos_tbl = sa.table(
        "viv_ml_proyectos",
        sa.column("id", sa.String()),
        sa.column("tipo", sa.String()),
        sa.column("nombre", sa.String()),
        sa.column("localidad_nombre", sa.String()),
        sa.column("expediente", sa.String()),
        sa.column("superficie", sa.Numeric()),
        sa.column("lotes", sa.Integer()),
        sa.column("ejuridico", sa.BigInteger()),
        sa.column("etecnico", sa.BigInteger()),
        sa.column("efinanciero", sa.BigInteger()),
        sa.column("monto", sa.Numeric()),
        sa.column("valor_fiscal", sa.Numeric()),
        sa.column("infra_sin_nexos", sa.Numeric()),
        sa.column("costo_nexos", sa.Numeric()),
        sa.column("convenio_unc", sa.Numeric()),
        sa.column("costo_total_infra", sa.Numeric()),
        sa.column("obs", sa.Text()),
        sa.column("ok_gob", sa.String()),
    )
    geo_tbl = sa.table(
        "viv_ml_geo_puntos",
        sa.column("id", sa.String()),
        sa.column("proyecto_id", sa.String()),
        sa.column("lat", sa.Numeric()),
        sa.column("lng", sa.Numeric()),
        sa.column("orden", sa.Integer()),
    )

    all_proy_rows = []
    all_geo_rows = []
    for proy in PROYECTOS_SEED:
        proy_id = str(uuid.uuid4())
        all_proy_rows.append({
            "id": proy_id,
            "tipo": proy["tipo"],
            "nombre": proy["nombre"],
            "localidad_nombre": proy["localidad_nombre"],
            "expediente": proy.get("expediente"),
            "superficie": proy.get("superficie"),
            "lotes": proy.get("lotes"),
            "ejuridico": proy.get("ejuridico"),
            "etecnico": proy.get("etecnico"),
            "efinanciero": proy.get("efinanciero"),
            "monto": proy.get("monto"),
            "valor_fiscal": proy.get("valor_fiscal"),
            "infra_sin_nexos": proy.get("infra_sin_nexos"),
            "costo_nexos": proy.get("costo_nexos"),
            "convenio_unc": proy.get("convenio_unc"),
            "costo_total_infra": proy.get("costo_total_infra"),
            "obs": proy.get("obs"),
            "ok_gob": "SI",
        })
        for i, geo in enumerate(proy.get("geo_puntos", []), start=1):
            all_geo_rows.append({
                "id": str(uuid.uuid4()),
                "proyecto_id": proy_id,
                "lat": geo["lat"],
                "lng": geo["lng"],
                "orden": i,
            })

    op.bulk_insert(proyectos_tbl, all_proy_rows)
    if all_geo_rows:
        op.bulk_insert(geo_tbl, all_geo_rows)


def downgrade() -> None:
    op.drop_table("viv_ml_pedidos")
    op.drop_table("viv_ml_estado_historial")
    op.drop_table("viv_ml_geo_puntos")
    op.drop_table("viv_ml_proyectos")
    op.drop_table("viv_ml_config")
    op.drop_table("viv_ml_estados")
