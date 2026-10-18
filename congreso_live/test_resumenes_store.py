"""Tests de congreso_live/resumenes_store.py."""
import congreso_live.resumenes_store as rs


def test_crea_y_actualiza(tmp_path, monkeypatch):
    destino = tmp_path / "data" / "transcripciones_resumenes.json"
    monkeypatch.setattr(rs, "_local_path", lambda: destino)
    assert rs.list_resumenes() == {}
    rs.guardar_resumen(video_id="abc123", resumen="Se debatio X",
                       ideas_clave=["Punto 1", "Punto 2"])
    r = rs.list_resumenes()
    assert r["abc123"]["resumen"] == "Se debatio X"
    assert r["abc123"]["ideas_clave"] == ["Punto 1", "Punto 2"]
    rs.guardar_resumen(video_id="abc123", resumen="Version actualizada",
                       ideas_clave=["Punto A"])
    r = rs.list_resumenes()
    assert len(r) == 1 and r["abc123"]["resumen"] == "Version actualizada"
    # Con path explicito lee ese archivo.
    assert rs.list_resumenes(destino) == r
    assert rs.list_resumenes(tmp_path / "no_existe.json") == {}


def test_resumen_como_lista(tmp_path):
    import json
    from congreso_live.resumenes_store import list_resumenes
    p = tmp_path / "r.json"
    p.write_text(json.dumps([{"video_id": "x", "resumen": ["a", "b"], "ideas_clave": None}]), encoding="utf-8")
    r = list_resumenes(p)["x"]
    assert r["resumen"] == "a\n\nb" and r["ideas_clave"] == []
