"""Tests de congreso_live/qa_chat.py (sin red)."""
import pytest

from congreso_live.qa_chat import preguntar


def test_exige_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        preguntar("test", "texto de prueba")
