from auth import store as auth_store
from core import store


def test_register_local_idempotente(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store._cache.clear()

    assert auth_store.register("Nico@Vali.com ") is True
    assert auth_store.register("nico@vali.com") is False
    assert auth_store.is_registered("NICO@vali.com")
    store._cache.clear()
    assert [u["email"] for u in auth_store.list_users()] == ["nico@vali.com"]
