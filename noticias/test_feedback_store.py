import base64
import json
from unittest.mock import patch

from core import store
from noticias.feedback_store import deshacer_descarte, list_descartadas, registrar_descarte


def test_descartes_locales(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "_cache", {})

    assert registrar_descarte(101, descartado_por="nico")
    assert list_descartadas() == {101}
    registrar_descarte(101, descartado_por="nico")
    assert list_descartadas() == {101}, "no debe duplicar la misma noticia_id"
    registrar_descarte(202)
    assert list_descartadas() == {101, 202}
    assert deshacer_descarte(101)
    assert list_descartadas() == {202}
    assert deshacer_descarte(999)  # no estaba descartada: no falla
    assert list_descartadas() == {202}
    guardado = json.loads((tmp_path / "data" / "noticias_feedback.json").read_text(encoding="utf-8"))
    assert [d["noticia_id"] for d in guardado] == [202]


def test_descartar_con_github_no_relee(monkeypatch):
    """Un click = GET + PUT. El rerun inmediato de Streamlit usa el cache que
    dejo el PUT, sin un 3er round-trip."""
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("GH_REPO", "fake/repo")
    monkeypatch.setattr(store, "_cache", {})
    llamadas = []
    body = json.dumps({"content": base64.b64encode(b"[]").decode("ascii"), "sha": "abc123"}).encode()

    def fake_urlopen(req, timeout=None):
        llamadas.append(req.get_method())
        datos = b"{}" if req.get_method() == "PUT" else body
        return type("R", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None,
                              "read": lambda s: datos})()

    with patch("core.store.urllib.request.urlopen", side_effect=fake_urlopen):
        assert registrar_descarte(303, descartado_por="nico")
        assert llamadas == ["GET", "PUT"]
        assert list_descartadas() == {303}
        assert llamadas == ["GET", "PUT"]
