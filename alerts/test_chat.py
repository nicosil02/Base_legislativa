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


def test_enlaces_se_leen_y_503_pasa_al_respaldo(monkeypatch):
    """3/11/2026: el redactor no abria enlaces/PDF y un 503 cortaba la conversacion."""
    from alerts import chat
    from core import llm
    monkeypatch.setattr(chat, "leer_enlace", lambda u: f"TEXTO DE {u}")
    assert "TEXTO DE https://a.gob/x.pdf" in chat.con_enlaces("mira https://a.gob/x.pdf.")
    assert chat.con_enlaces("sin enlaces") == "sin enlaces"
    assert "<b>" not in chat._texto_html("<script>x</script><article><p>Hola <b>mundo</b></p></article>")

    usados = []
    class Chat:
        def __init__(self, m): self.m = m
        def send_message(self, t):
            usados.append((self.m, t))
            if self.m == llm.FLASH:
                raise RuntimeError("503 UNAVAILABLE")
            return type("R", (), {"text": "ok"})()
    monkeypatch.setattr(chat, "nueva_conversacion", lambda s, historial=None, modelo=None: (None, Chat(modelo)))
    monkeypatch.setattr(llm, "ESPERAS", (0,))
    assert chat.responder("bayer", [["user", "ver https://b.pe"]], "dale")[0] == "ok"
    assert usados[-1][0] == llm.LITE
