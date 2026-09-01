"""Unit tests del port de v_informe_cooperativas (Anexo A)."""
import pytest

from app.informe.clasificacion import entra_al_informe, es_ministerio_cooperativas, tema_informe

MC = "MIN_COOPERATIVAS_MUTUALES"
OTRO = "MIN_GOBIERNO"


@pytest.mark.parametrize("cat,detalle,min_id,esperado", [
    ("CAT_INFRAESTRUCTURA_VIAL", "OBRA DE CORDON CUNETA EN BARRIO X", OTRO, "Cordón Cuneta + Adoquinado"),
    ("CAT_INFRAESTRUCTURA_VIAL", "adoquinado de calle principal", OTRO, "Cordón Cuneta + Adoquinado"),
    ("CAT_INFRAESTRUCTURA_VIAL", "ciclovia y señalizacion", OTRO, None),  # vial sin keyword -> fuera
    ("CAT_OBRA_ELECTRICA_ENERGIA", "provision de KIT SOLAR para escuela", OTRO, "Kits Solares"),
    ("CAT_OBRA_ELECTRICA_ENERGIA", "recambio de luminarias led", OTRO, "Luces LED"),
    ("CAT_OBRA_ELECTRICA_ENERGIA", "tendido de red electrica rural", OTRO, "Infraestructura Eléctrica"),
    ("CAT_OBRA_DE_GAS", "cualquier cosa", OTRO, "Gas"),
    ("CAT_AGUA_Y_SANEAMIENTO", "pantallas solares para bomba de agua", OTRO, "Bombeo Solar"),
    ("CAT_OTROS", "construccion de viviendas sociales", OTRO, "Vivienda"),
    ("CAT_OTROS", "regularizacion dominial de lotes", OTRO, "Lotes"),
    ("CAT_OTROS", "linea de credito para fortalecimiento de cooperativa", MC, "Préstamos y Fortalecimiento"),
    ("CAT_OTROS", "algo sin keywords", MC, "Otras Obras"),
    ("CAT_OTROS", "algo sin keywords", OTRO, None),
])
def test_tema_informe(cat, detalle, min_id, esperado):
    assert tema_informe(cat, detalle, min_id) == esperado


def test_prioridad_cuneta_antes_que_vivienda():
    # 'vivienda' + 'cuneta' en vial -> gana Cordón Cuneta (prioridad 1)
    assert tema_informe("CAT_INFRAESTRUCTURA_VIAL", "cuneta para el barrio de viviendas", OTRO) == "Cordón Cuneta + Adoquinado"


def test_es_ministerio_cooperativas():
    assert es_ministerio_cooperativas(MC) is True
    assert es_ministerio_cooperativas(OTRO) is False
    assert es_ministerio_cooperativas(None) is False


def test_entra_al_informe():
    assert entra_al_informe("CAT_OTROS", "nada", MC) == (True, "Otras Obras")
    assert entra_al_informe("CAT_OTROS", "nada", OTRO) == (False, None)
    assert entra_al_informe("CAT_OBRA_DE_GAS", "gas", OTRO) == (True, "Gas")
    assert entra_al_informe(None, "vivienda social", OTRO) == (True, "Vivienda")
