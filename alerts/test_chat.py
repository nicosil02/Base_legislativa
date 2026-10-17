"""alerts/chat.py sin red."""
import pytest

from core import llm
from alerts.chat import construir_system_prompt, nueva_conversacion


@pytest.fixture
def sin_cliente(monkeypatch):
    monkeypatch.setattr(llm, "_cliente", None)


def test_system_prompt_con_contexto_real():
    prompt = construir_system_prompt("bayer")
    for parte in ("PERFIL DEL CLIENTE", "FORMATO Y REGLAS EXACTAS", "EJEMPLOS REALES"):
        assert parte in prompt
    assert "(sin notas.md" not in prompt
    assert "(sin notas.md para este cliente)" in construir_system_prompt("cliente_que_no_existe")


def test_exige_api_key(sin_cliente, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        nueva_conversacion("bayer")


def test_reconstruye_con_historial(sin_cliente, monkeypatch):
    pytest.importorskip("google.genai")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    historial = [{"role": "user", "parts": [{"text": "hola"}]},
                 {"role": "model", "parts": [{"text": "hola, en que te ayudo"}]}]
    client, chat = nueva_conversacion("bayer", historial=historial)
    assert client is llm.cliente()
    assert len(chat.get_history()) == 2
