import pytest

from clientes import privado


def test_ida_y_vuelta_y_clave_equivocada(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIENTES_CLAVE", "una")
    datos = "Perfil de Bayer: medicamentos genéricos".encode() * 50 + bytes(range(256))
    c = privado.cifrar(datos)
    assert b"Bayer" not in c.encode() and privado.descifrar(c) == datos
    assert privado.cifrar(datos) != c  # nonce aleatorio
    monkeypatch.setenv("CLIENTES_CLAVE", "otra")
    with pytest.raises(ValueError):
        privado.descifrar(c)


def test_cerrar_y_abrir(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIENTES_CLAVE", "una")
    (tmp_path / "bayer").mkdir()
    notas = tmp_path / "bayer" / "notas.md"
    notas.write_text("perfil", encoding="utf-8")
    (tmp_path / "reporte.docx").write_text("no va al repo")
    assert privado.cerrar(tmp_path) == 1
    assert privado.cerrar(tmp_path) == 0  # sin cambios no reescribe
    assert not (tmp_path / "reporte.docx.cifrado").exists()
    notas.unlink()
    assert privado.abrir(carpeta=tmp_path) == 1 and notas.read_text(encoding="utf-8") == "perfil"
    monkeypatch.delenv("CLIENTES_CLAVE")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    notas.unlink()
    assert privado.abrir(carpeta=tmp_path) == 0  # sin clave no hace nada
