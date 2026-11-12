"""Construcción del cliente según el proveedor (spec changelog 1.0.2). Sin red."""
import pytest

from app.agente import llm
from app.config import settings


def test_anthropic_con_api_key(monkeypatch):
    monkeypatch.setattr(settings, "proveedor_llm", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    from anthropic import AsyncAnthropic
    assert isinstance(llm.ClienteClaude()._c, AsyncAnthropic)


def test_anthropic_sin_api_key_falla_claro(monkeypatch):
    monkeypatch.setattr(settings, "proveedor_llm", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.ClienteClaude()


def test_vertex_sigue_disponible(monkeypatch):
    monkeypatch.setattr(settings, "proveedor_llm", "vertex")
    from anthropic import AsyncAnthropicVertex
    assert isinstance(llm.ClienteClaude()._c, AsyncAnthropicVertex)
