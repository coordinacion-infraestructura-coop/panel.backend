"""Listado (dimension) de los estados de los paneles CC / CH / ML.

Cada estado de `viv_cc_estados` / `viv_ch_estados` / `viv_ml_estados` pertenece a un solo
listado (spec-vivienda-estados-por-area.md §2). Al guardar una entidad, cada columna de
estado tiene que apuntar a un estado de su listado.
"""
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

Dimension = Literal["juridico", "financiero", "general", "tecnico_anterior"]
# Los que se pueden crear desde el administrador; `tecnico_anterior` solo existe por la migración 0044.
DimensionEditable = Literal["juridico", "financiero", "general"]

DIMENSION_DE_CAMPO: dict[str, str] = {
    "ejuridico": "juridico",
    "efinanciero": "financiero",
    "estado_general": "general",
}


async def validar_dimensiones(db: AsyncSession, modelo_estado, valores: dict) -> None:
    """422 si alguno de `ejuridico` / `efinanciero` / `estado_general` en `valores` no es de su listado."""
    pedidos = {
        campo: valores[campo] for campo in DIMENSION_DE_CAMPO
        if valores.get(campo) is not None
    }
    if not pedidos:
        return
    filas = (await db.execute(
        select(modelo_estado.id, modelo_estado.dimension).where(modelo_estado.id.in_(set(pedidos.values())))
    )).all()
    dimension_de = {id_: dim for id_, dim in filas}
    for campo, estado_id in pedidos.items():
        esperada = DIMENSION_DE_CAMPO[campo]
        if dimension_de.get(estado_id) != esperada:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "ESTADO_DE_OTRO_LISTADO",
                    "message": f"El estado {estado_id} no pertenece al listado '{esperada}' ({campo}).",
                },
            )
