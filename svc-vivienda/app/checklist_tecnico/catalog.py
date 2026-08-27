"""Catálogo de ítems de checklist por programa — hardcodeado, no administrable (spec §4).

A diferencia de "Estado del expediente" y "Repartición" (tablas, editables por Admin),
las etiquetas de los ítems de documentación son fijas en código, igual que hizo el sync
de Cordón Cuneta (`spec-sync-cc-checklist-tecnico.md` §5.2).
"""
from typing import Literal

Programa = Literal["cc", "ch", "ml"]
ValorItem = Literal["sin_presentar", "eval_tecnica", "a_corregir", "eval_juridica", "completo"]
TipoHito = Literal["anticipo", "40", "70", "100"]

VALORES_ITEM: tuple[ValorItem, ...] = ("sin_presentar", "eval_tecnica", "a_corregir", "eval_juridica", "completo")
PROGRAMAS: tuple[Programa, ...] = ("cc", "ch", "ml")

CC_ITEMS: dict[int, str] = {
    1: "Nota de Solicitud de Financiamiento",
    2: "Ordenanza y Decreto / Resolución comunal",
    3: "DDJJ compromiso de ejecución de obra",
    4: "Proyecto, Planos, Cómputo y Presupuesto",
    5: "Nota a Contaduría — Cesión de Coparticipación",
    6: "N° de CBU de M/C especial para depósito de fondos",
    7: "N° de CUIT Municipal / Comunal",
    8: "DNI Intendente / Jefe Comunal",
    9: "Acta de Proclamación Int. / Pres. Comunal",
}
CC_SUB_ITEM4: dict[int, str] = {
    1: "Descripción General",
    2: "Memoria Técnica",
    3: "Plazo de Ejecución",
    4: "Cómputo y Presupuesto",
    5: "Cronograma de Avance de Obra",
    6: "Planimetría",
    7: "Perfil de Calzada",
    8: "Detalle de Cordón Cuneta",
    9: "Detalle de Badén",
    10: "Paquete estructural de Calzada",
}

CH_ITEMS: dict[int, str] = {
    1: "Planimetría (Ubicación de Obra)",
    2: "Matrícula de cada lote",
    3: "Estudio de Suelo",
    4: "Certificado de No Inundabilidad",
    5: "Factibilidad de Agua Potable",
    6: "Factibilidad de Energía Eléctrica",
    7: "Designación de Director Técnico de Obra",
    8: "Memoria Técnica descriptiva",
    9: "Planos Legajo Técnico",
    10: "Pliego de Especificaciones Técnicas",
    11: "Cómputo y Presupuesto",
    12: "Acta de Medición - Certificado",
    13: "Curva de Avance",
    14: "Cronograma de Avance",
}

ML_ITEMS: dict[int, str] = {
    1: "Planimetría General",
    2: "Plano de Altimetría",
    3: "Plancheta Catastral",
    4: "Títulos",
    5: "Certificado de No Inundabilidad",
    6: "Informe de Ministerio de Ambiente y Economía Circular",
    7: "Factibilidad de Agua Potable",
    8: "Factibilidad de Energía Eléctrica",
    9: "Certificado de Prestación de Servicios",
    10: "Factibilidad de Red Cloacal / Pozo Absorbente",
    11: "Designación de Representante Técnico",
    12: "Plano de Loteo Aprobado y Protocolizado",
    13: "Ordenanza / Resolución",
    14: "Proyectos de infraestructura a realizar",
}
ML_SUB_ITEM14: dict[int, str] = {
    1: "Red Vial",
    2: "Red de Agua Potable",
    3: "Red Energía Eléctrica — Media y Baja Tensión",
    4: "Red de Alumbrado Público",
    5: "Nexo de Agua",
    6: "Nexo Eléctrico",
}

# item_num que se abre en sub-ítems, por programa (None si el programa no tiene ninguno)
_ITEM_CON_SUBITEMS: dict[str, int | None] = {"cc": 4, "ch": None, "ml": 14}

_ITEMS_POR_PROGRAMA: dict[str, dict[int, str]] = {"cc": CC_ITEMS, "ch": CH_ITEMS, "ml": ML_ITEMS}
_SUBITEMS_POR_PROGRAMA: dict[str, dict[int, str]] = {"cc": CC_SUB_ITEM4, "ml": ML_SUB_ITEM14}

HITOS_TIPOS: tuple[TipoHito, ...] = ("anticipo", "40", "70", "100")
HITOS_LABEL: dict[str, str] = {
    "anticipo": "Anticipo financiero",
    "40": "Avance físico 40%",
    "70": "Avance físico 70%",
    "100": "Avance físico 100%",
}
# Confirmado empíricamente sobre la planilla real (spec §5.5): 50/25/25 + saldo.
HITOS_PORCENTAJE: dict[str, float] = {"anticipo": 0.5, "40": 0.25, "70": 0.25, "100": 0.0}


def item_label(programa: str, item_num: int, sub_item_num: int | None) -> str | None:
    """Label de un ítem o sub-ítem, o None si el número no existe para ese programa."""
    if sub_item_num is not None:
        return _SUBITEMS_POR_PROGRAMA.get(programa, {}).get(sub_item_num)
    return _ITEMS_POR_PROGRAMA.get(programa, {}).get(item_num)


def items_definition(programa: str) -> list[dict]:
    """[{item_num, label, sub_items: [{sub_item_num, label}] | None}, ...] para el selector de catálogo."""
    items = _ITEMS_POR_PROGRAMA.get(programa, {})
    subitem_de = _ITEM_CON_SUBITEMS.get(programa)
    subitems = _SUBITEMS_POR_PROGRAMA.get(programa, {})
    result = []
    for num, label in items.items():
        sub_items = None
        if num == subitem_de:
            sub_items = [{"sub_item_num": s_num, "label": s_label} for s_num, s_label in subitems.items()]
        result.append({"item_num": num, "label": label, "sub_items": sub_items})
    return result


def todos_los_item_keys(programa: str) -> list[tuple[int, int | None]]:
    """Lista completa de (item_num, sub_item_num) para inicializar un checklist nuevo."""
    keys: list[tuple[int, int | None]] = []
    items = _ITEMS_POR_PROGRAMA.get(programa, {})
    subitem_de = _ITEM_CON_SUBITEMS.get(programa)
    subitems = _SUBITEMS_POR_PROGRAMA.get(programa, {})
    for num in items:
        keys.append((num, None))
        if num == subitem_de:
            keys.extend((num, s_num) for s_num in subitems)
    return keys
