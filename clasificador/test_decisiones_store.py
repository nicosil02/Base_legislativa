from clasificador import decisiones_store as ds
from core import store


def test_upsert_y_limpieza_local(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store._cache.clear()

    assert ds.registrar_decision(sugerencia_id=1, decision="aceptar", decided_by="nico")
    assert [d["decision"] for d in ds.list_decisiones_pendientes()] == ["aceptar"]

    # Cambiar de opinión actualiza, no duplica.
    ds.registrar_decision(sugerencia_id=1, decision="rechazar", decided_by="nico")
    assert [d["decision"] for d in ds.list_decisiones_pendientes()] == ["rechazar"]

    ds.registrar_decision(sugerencia_id=2, decision="aceptar")
    assert len(ds.list_decisiones_pendientes()) == 2

    ds.limpiar_decisiones_aplicadas([1])
    assert [d["sugerencia_id"] for d in ds.list_decisiones_pendientes()] == [2]
