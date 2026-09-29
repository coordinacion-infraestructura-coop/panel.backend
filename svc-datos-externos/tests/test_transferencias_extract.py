"""Tests unitarios del parser de PDF — solo las funciones puras (sin
pdfplumber real, que requiere un PDF de verdad). Cubren los 3 hallazgos
reales documentados en spec-resumen-territorial-tablero-v2.md §2.3: nombre
con dígito, colisión "TOTAL GENERAL"/"TOTAL General Roca", y tolerancia de
redondeo en la validación de sumas."""
from app.transferencias import extract


def _tok(text: str, x0: float) -> dict:
    return {"text": text, "x0": x0}


def test_normalize_name_quita_acentos_y_puntuacion():
    assert extract.normalize_name("Río Cuarto") == "RIO CUARTO"
    assert extract.normalize_name("  Villa   María  ") == "VILLA MARIA"


def test_classify_line_data_row():
    assert extract.classify_line("Alta Gracia", "Alta Gracia 1 2 3 4 5 6", 6) == "data"


def test_classify_line_header_or_dept_pocos_tokens_numericos():
    # menos de MIN_NUM_TOKENS numéricos -> no es una fila de datos real
    assert extract.classify_line("Departamento Colón", "Departamento Colón", 0) == "header_or_dept"


def test_classify_line_boilerplate_con_digitos_sueltos():
    # título/nota con algún dígito (ej. el año), pero no 6 montos
    assert extract.classify_line("Recaudación 2026", "Recaudación 2026", 1) == "boilerplate"


def test_classify_line_grand_total_exacto():
    assert extract.classify_line("TOTAL GENERAL", "TOTAL GENERAL 1 2 3 4 5 6", 6) == "grand_total"


def test_classify_line_dept_total():
    assert extract.classify_line("TOTAL Calamuchita", "TOTAL Calamuchita 1 2 3 4 5 6", 6) == "dept_total"


def test_classify_line_general_roca_no_es_grand_total():
    """Bug real encontrado y corregido: 'TOTAL General Roca' no debe
    clasificarse como 'TOTAL GENERAL' (colisión de prefijo con un
    departamento real llamado 'General Roca')."""
    assert extract.classify_line("TOTAL General Roca", "TOTAL General Roca 1 2 3 4 5 6", 6) == "dept_total"


def test_split_name_numeric_separa_nombre_y_montos():
    tokens = [_tok("Alta", 10), _tok("Gracia", 40), _tok("1.234", 100), _tok("5.678", 200)]
    name, num_tokens = extract.split_name_numeric(tokens)
    assert name == "Alta Gracia"
    assert [t["text"] for t in num_tokens] == ["1.234", "5.678"]


def test_assign_to_bins_reconstruye_numero_fragmentado():
    """Un TOTAL de departamento (más ancho) puede partirse en 2 tokens de
    texto por el mismo monto — se reconstruye por posición, no por texto."""
    bins = [(90.0, 150.0), (151.0, 250.0), (251.0, 350.0), (351.0, 450.0), (451.0, 550.0), (551.0, float("inf"))]
    num_tokens = [
        _tok("1.234", 100), _tok(".567", 120),  # fragmentado en 2 dentro del mismo bin
        _tok("100", 200), _tok("200", 300), _tok("300", 400), _tok("400", 500), _tok("500", 600),
    ]
    montos, nombre_extra = extract.assign_to_bins(num_tokens, bins)
    assert montos == [1234567, 100, 200, 300, 400, 500]
    assert nombre_extra == ""


def test_assign_to_bins_numero_en_el_nombre_no_corrompe_montos():
    """Bug real encontrado y corregido: 'KILOMETRO 658' (comuna real) no debe
    tratarse como el inicio de los montos."""
    bins = [(90.0, 150.0), (151.0, 250.0), (251.0, 350.0), (351.0, 450.0), (451.0, 550.0), (551.0, float("inf"))]
    num_tokens = [
        _tok("658", 20),  # parte del nombre, muy a la izquierda del primer bin
        _tok("100", 100), _tok("200", 200), _tok("300", 300), _tok("400", 400), _tok("500", 500), _tok("600", 600),
    ]
    montos, nombre_extra = extract.assign_to_bins(num_tokens, bins)
    assert montos == [100, 200, 300, 400, 500, 600]
    assert nombre_extra == "658"


def test_validar_totales_sin_discrepancias():
    filas = [
        {"departamento_pdf": "Colón", "concepto": "total", "monto": 100},
        {"departamento_pdf": "Colón", "concepto": "total", "monto": 200},
    ]
    totales_depto = {"COLON": {"total": 300}}
    errores = extract.validar_totales(filas, totales_depto, None)
    assert errores == []


def test_validar_totales_tolera_pequeno_redondeo():
    filas = [{"departamento_pdf": "Colón", "concepto": "total", "monto": 299}]
    totales_depto = {"COLON": {"total": 300}}  # diferencia de 1, dentro de tolerancia=50
    assert extract.validar_totales(filas, totales_depto, None) == []


def test_validar_totales_reporta_discrepancia_fuera_de_tolerancia():
    filas = [{"departamento_pdf": "Colón", "concepto": "total", "monto": 100}]
    totales_depto = {"COLON": {"total": 300}}  # diferencia de 200
    errores = extract.validar_totales(filas, totales_depto, None)
    assert len(errores) == 1
    assert "COLON" in errores[0]
