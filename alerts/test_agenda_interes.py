import json
import sqlite3

from alerts import agenda_interes as ai

SES = {"clave": "ec:1", "pais": "EC", "nombre": "Comisión de Derecho a la Salud (Asamblea EC)",
       "fecha": "2026-10-20", "hora": "09:00", "texto": "Proyecto de Ley de medicamentos genéricos", "hash": "h1"}


def test_juzgar_pasa_lo_ya_avisado_y_devuelve_solo_puntos():
    vistos = []

    def falso(prompt, **k):
        vistos.append(prompt)
        return json.dumps([{"indice": 1, "puntos": [{"texto": "PL de genéricos", "clientes": ["bayer"]}]}])

    out = ai.juzgar([SES], {"ec:1": ["Invitado del MSP"]}, falso)
    assert out == {1: [{"texto": "PL de genéricos", "clientes": ["bayer"]}]}
    assert "YA AVISADO" in vistos[0] and "Invitado del MSP" in vistos[0]
    assert "=== google ===" not in vistos[0]  # Google es solo PE


def test_run_avisa_una_vez_por_version(monkeypatch, tmp_path):
    cerebro = sqlite3.connect(tmp_path / "c.db")
    monkeypatch.setattr("cerebro.embeddings.conectar", lambda: cerebro)
    actual = dict(SES)
    monkeypatch.setattr(ai, "sesiones", lambda h, d: [actual])
    llamadas = []

    def falso(prompt, **k):
        llamadas.append(prompt)
        return json.dumps([{"indice": 1, "puntos": [{"texto": "PL de genéricos", "clientes": ["bayer"]}]}])

    texto = ai.run(enviar=False, generar=falso)
    assert "*Comisión de Derecho a la Salud (Asamblea EC)* · 20/10 09:00" in texto and "(Bayer)" in texto
    assert ai.run(enviar=False, generar=falso) is None and len(llamadas) == 1  # misma version: no se juzga
    actual["hash"] = "h2"
    assert "(agenda actualizada)" in ai.run(enviar=False, generar=falso)
    assert "PL de genéricos" in llamadas[-1]  # lo ya avisado va al prompt


def test_sin_interes_no_hay_mensaje(monkeypatch, tmp_path):
    cerebro = sqlite3.connect(tmp_path / "c.db")
    monkeypatch.setattr("cerebro.embeddings.conectar", lambda: cerebro)
    monkeypatch.setattr(ai, "sesiones", lambda h, d: [dict(SES)])
    assert ai.run(enviar=False, generar=lambda p, **k: json.dumps([{"indice": 1, "puntos": []}])) is None
