"""seguimiento_store en modo local (sin GitHub)."""
from core import store
from alerts.seguimiento_store import list_seguidas, set_seguidas


def test_seguimiento_guarda_y_lee(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "_cache", {})
    assert list_seguidas() == set()
    set_seguidas({"Comision: Salud", "Comision: Economia"})
    store._cache.clear()
    assert list_seguidas() == {"Comision: Salud", "Comision: Economia"}
