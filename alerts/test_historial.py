from alerts import historial
from core import store


def test_agregar_y_leer(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(historial, "ROOT", tmp_path)
    e = historial.entrada("Minsa en reorganización", "*Texto* de la alerta", "Perú",
                          url="https://x.pe/1", linea="Farma", fecha="2026-10-17")
    assert e.startswith("## 2026-10-17 — Farma — Perú\n**Minsa en reorganización**\n")
    historial.agregar("bayer", e)
    historial.agregar("bayer", historial.entrada("Otra", "texto", "Ecuador", fecha="2026-10-18"))
    es = historial.entradas("bayer")
    assert [x["fecha"] for x in es] == ["2026-10-17", "2026-10-18"]
    assert es[0]["encabezado"] == "2026-10-17 — Farma — Perú"
    assert "Fuente: https://x.pe/1" in es[0]["cuerpo"]
    assert es[1]["cuerpo"] == "**Otra**\ntexto"


def test_entradas_del_historial_real():
    # El formato real (con preambulo y ---) se parte bien por encabezado.
    es = historial.entradas("x", "# T\n\nintro\n\n---\n\n## 2026-09-11 — Crop — Perú\n**A**\nuno\n\n"
                                 "## 2026-09-12 — Farma — Ecuador\n**B**\ndos\n")
    assert len(es) == 2 and es[1]["cuerpo"] == "**B**\ndos"


def test_clientes_por_pais(tmp_path, monkeypatch):
    monkeypatch.setattr(historial, "ROOT", tmp_path)
    for slug, linea in [("google", "Países: PE\n"), ("bayer", "Países: PE, EC\n"), ("nuevo", "")]:
        (tmp_path / "clientes" / slug).mkdir(parents=True)
        (tmp_path / "clientes" / slug / "notas.md").write_text(f"# {slug}\n\n{linea}", encoding="utf-8")
    (tmp_path / "clientes" / "reportes").mkdir()
    assert historial.clientes() == ["bayer", "google", "nuevo"]
    assert historial.clientes("EC") == ["bayer", "nuevo"]
