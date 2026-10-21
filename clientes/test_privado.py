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


def test_buzon_ida_y_vuelta_y_recibir_cifra(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from clientes import privado
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = tmp_path / "buzon.pub"
    pub.write_bytes(k.public_key().public_bytes(serialization.Encoding.PEM,
                                                serialization.PublicFormat.SubjectPublicKeyInfo))
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "notas.md").write_text("perfil de acme", encoding="utf-8")
    (tmp_path / "acme" / "borrador.docx").write_text("no va", encoding="utf-8")

    hechos = privado.enviar([tmp_path / "acme"], carpeta=tmp_path, publica=pub)
    assert [b.name for b in hechos] == ["notas.md.buzon"]  # solo archivos de datos
    assert b"perfil" not in hechos[0].read_bytes()

    (tmp_path / "acme" / "notas.md").unlink()  # en CI no existe el texto
    monkeypatch.setenv("CLIENTES_BUZON", priv.decode())
    monkeypatch.setenv("CLIENTES_CLAVE", "prueba")
    assert privado.recibir(tmp_path) == 1
    assert not hechos[0].exists()
    cif = (tmp_path / "acme" / "notas.md.cifrado").read_text(encoding="ascii")
    assert privado.descifrar(cif) == b"perfil de acme"
