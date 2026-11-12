import pytest

from app.semantica.glosario import enmascarar, estado_normalizado, url_ficha


def test_mapeo_privada_exacto():
    assert estado_normalizado("privada", "INGRESADO") == "Sin iniciar"
    assert estado_normalizado("privada", "DERIVADO A SUAC") == "En trámite"
    assert estado_normalizado("privada", "FINALIZADA") == "Finalizado"
    assert estado_normalizado("privada", "ARCHIVADO") == "Trabado/Suspendido"
    assert estado_normalizado("privada", "OTRO") == "En trámite"


def test_mapeo_vivienda_por_reglas():
    assert estado_normalizado("vivienda", "Obra finalizada") == "Finalizado"
    assert estado_normalizado("vivienda", "En ejecución de obra") == "En ejecución"
    assert estado_normalizado("vivienda", "Convenio SUSPENDIDO") == "Trabado/Suspendido"
    assert estado_normalizado("vivienda", "Convenio en firma") == "En trámite"
    assert estado_normalizado("vivienda", None) == "Sin iniciar"


def test_mapeo_atp():
    assert estado_normalizado("atp", "Parcial") == "En ejecución"
    assert estado_normalizado("atp", "Pagado") == "Finalizado"


def test_enmascarar_datos_personales():
    t = enmascarar("Juan 351-555-1234, DNI 30.123.456 o 30123456, juan.p@mail.com, CUIT 20-30123456-7, +54 9 351 4567890")
    assert "351-555-1234" not in t and "30.123.456" not in t and "30123456" not in t
    assert "juan.p@mail.com" not in t and "20-30123456-7" not in t and "4567890" not in t
    assert "[teléfono]" in t and "[dni]" in t and "[email]" in t and "[cuit]" in t


def test_enmascarar_conserva_montos_y_anios():
    t = enmascarar("Presupuesto $ 1.500.000 para 2026, calle 25 de Mayo 123")
    assert "$ 1.500.000" in t and "2026" in t and "123" in t


def test_url_ficha():
    assert url_ficha("General San Martín", "Villa María") == "/resumen-territorial/General%20San%20Mart%C3%ADn/Villa%20Mar%C3%ADa"
    assert url_ficha(None, "x") is None


@pytest.mark.parametrize("estado,esperado", [
    ("Cumplido", "Finalizado"), ("A EJECUTAR", "Sin iniciar"), ("Pendiente", "Sin iniciar"),
    ("EN EJECUCIÓN", "En ejecución"), ("FINALIZADA", "Finalizado"),
])
def test_estados_reales_de_gasifera(estado, esperado):
    assert estado_normalizado("gasifera", estado) == esperado
