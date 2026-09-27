"""Self-check minimo de la logica de scheduling de alerts/cli.py.

Uso: python -m alerts.test_cli
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import alerts.build  # noqa: F401 - necesario para que patch() resuelva "alerts.build.*"
import alerts.cli as cli
import alerts.send  # noqa: F401 - necesario para que patch() resuelva "alerts.send.*"


def _fake_payload():
    # Sin contenido real - lo que importa aca es la logica de envio/estado,
    # no el contenido del email (eso ya lo cubre alerts/build.py aparte).
    return {"fecha": "2026-09-20", "peru": {"dictamenes": [], "proyectos": [{"pl": "1"}], "sesiones": []},
            "ecuador": {"dictamenes": [], "proyectos": [], "sesiones": []}}


def _payload_vacio():
    return {"fecha": "2026-09-20", "peru": {"dictamenes": [], "proyectos": [], "sesiones": []},
            "ecuador": {"dictamenes": [], "proyectos": [], "sesiones": []}}


def test_sin_novedades_no_envia_ni_marca_el_slot():
    """Nicolas 2026-09-27: "si no hay actualizaciones, no me envies nada".
    Sin contenido no se manda, y el slot no queda marcado (la ventana del
    proximo envio sigue siendo desde el ultimo correo REAL)."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "alert_sent_log.json"
        enviados = []
        with patch.object(cli, "STATE_FILE", state_file),              patch.object(cli, "_today_str", lambda: "2026-09-20"),              patch("alerts.build.build_alert", lambda since_iso=None: _payload_vacio()),              patch("alerts.send.send_email", lambda subject, html, recipient: enviados.append(recipient)),              patch.object(cli, "_list_recipients", lambda: ["nico@example.com"]):
            assert cli.main(["send", "--slot", "am"]) == 0
        assert enviados == [], "sin novedades no debe enviar"
        assert not state_file.exists(), "no debe marcar el slot como enviado"


def test_no_duplica_el_mismo_slot_el_mismo_dia():
    """Un rerun/retry del workflow no debe mandar 2 veces el mismo horario."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "alert_sent_log.json"
        enviados = []
        with patch.object(cli, "STATE_FILE", state_file), \
             patch.object(cli, "_today_str", lambda: "2026-09-20"), \
             patch("alerts.build.build_alert", lambda since_iso=None: _fake_payload()), \
             patch("alerts.send.send_email", lambda subject, html, recipient: enviados.append(recipient)), \
             patch.object(cli, "_list_recipients", lambda: ["nico@example.com"]):
            cli.main(["send", "--slot", "am"])
            cli.main(["send", "--slot", "am"])  # rerun del mismo slot
        assert len(enviados) == 1, "no debe re-enviar el mismo slot dos veces el mismo dia"


def test_am_y_pm_son_independientes():
    """El slot 'pm' no debe quedar bloqueado porque ya se mando el 'am'
    (bug del esquema viejo: un solo flag 'sent' por dia, no por slot)."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "alert_sent_log.json"
        enviados = []
        with patch.object(cli, "STATE_FILE", state_file), \
             patch.object(cli, "_today_str", lambda: "2026-09-20"), \
             patch("alerts.build.build_alert", lambda since_iso=None: _fake_payload()), \
             patch("alerts.send.send_email", lambda subject, html, recipient: enviados.append(recipient)), \
             patch.object(cli, "_list_recipients", lambda: ["nico@example.com"]):
            cli.main(["send", "--slot", "am"])
            cli.main(["send", "--slot", "pm"])
        assert len(enviados) == 2, "am y pm deben enviar cada uno, son horarios distintos"
        estado = json.loads(state_file.read_text(encoding="utf-8"))
        assert set(estado["2026-09-20"].keys()) == {"am", "pm"}


def test_manual_no_marca_estado():
    """'manual' siempre envia (para pruebas) y no interfiere con el dedupe de am/pm."""
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "alert_sent_log.json"
        enviados = []
        with patch.object(cli, "STATE_FILE", state_file), \
             patch.object(cli, "_today_str", lambda: "2026-09-20"), \
             patch("alerts.build.build_alert", lambda since_iso=None: _fake_payload()), \
             patch("alerts.send.send_email", lambda subject, html, recipient: enviados.append(recipient)), \
             patch.object(cli, "_list_recipients", lambda: ["nico@example.com"]):
            cli.main(["send", "--slot", "manual"])
            cli.main(["send", "--slot", "am"])
        assert len(enviados) == 2, "manual no debe bloquear el envio real del slot am"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
