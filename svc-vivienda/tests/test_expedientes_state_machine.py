"""
Tests de la máquina de estados de expedientes.
Estos tests no requieren DB — validan la lógica de transiciones pura.
"""
import pytest

from app.expedientes.models import EstadoExpediente, TRANSICIONES_VALIDAS


def test_todas_las_transiciones_definidas():
    for estado in EstadoExpediente:
        assert estado in TRANSICIONES_VALIDAS, f"Estado {estado} no tiene transiciones definidas"


def test_transicion_ingresado_a_evaluacion():
    assert EstadoExpediente.EN_EVALUACION in TRANSICIONES_VALIDAS[EstadoExpediente.INGRESADO]


def test_transicion_evaluacion_puede_aprobar_rechazar_pedir_docs():
    permitidas = TRANSICIONES_VALIDAS[EstadoExpediente.EN_EVALUACION]
    assert EstadoExpediente.APROBADO in permitidas
    assert EstadoExpediente.RECHAZADO in permitidas
    assert EstadoExpediente.DOCUMENTACION_PENDIENTE in permitidas


def test_estado_baja_no_tiene_transiciones():
    assert TRANSICIONES_VALIDAS[EstadoExpediente.BAJA] == []


def test_rechazado_puede_reingresar():
    assert EstadoExpediente.INGRESADO in TRANSICIONES_VALIDAS[EstadoExpediente.RECHAZADO]


def test_transicion_lineal_asignacion():
    """APROBADO → EN_LISTA_ESPERA → ASIGNADO → BAJA"""
    assert EstadoExpediente.EN_LISTA_ESPERA in TRANSICIONES_VALIDAS[EstadoExpediente.APROBADO]
    assert EstadoExpediente.ASIGNADO in TRANSICIONES_VALIDAS[EstadoExpediente.EN_LISTA_ESPERA]
    assert EstadoExpediente.BAJA in TRANSICIONES_VALIDAS[EstadoExpediente.ASIGNADO]


def test_no_se_puede_saltar_estados():
    """No se puede ir de INGRESADO directo a APROBADO."""
    assert EstadoExpediente.APROBADO not in TRANSICIONES_VALIDAS[EstadoExpediente.INGRESADO]
    assert EstadoExpediente.ASIGNADO not in TRANSICIONES_VALIDAS[EstadoExpediente.INGRESADO]
