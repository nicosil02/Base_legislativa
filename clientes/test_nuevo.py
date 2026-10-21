import json

from clientes import config, nuevo


def test_crear_deja_ficha_y_temas_propios_cuentan(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CARPETA", tmp_path)
    nuevo.crear("minera", "Minera SA", ["PE"])
    ficha = json.loads((tmp_path / "minera" / "cliente.json").read_text(encoding="utf-8"))
    assert ficha["nombre"] == "Minera SA" and ficha["paises"] == ["PE"]
    assert (tmp_path / "minera" / "notas.md").read_text(encoding="utf-8").startswith("# Minera SA")

    ficha.update(temas_noticias=["Coyuntura política"], temas_propios={"Minería": ["concesion minera"]})
    monkeypatch.setattr(config, "todos", lambda: {"minera": ficha})
    assert config.temas_de("minera") == ["Coyuntura política", "Minería"]
    assert config.temas_propios() == {"Minería": ["concesion minera"]}
