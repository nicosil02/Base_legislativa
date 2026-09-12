"""Self-check minimo de alerts/relevancia.py (parseo de markdown, sin DB).

Uso: python -m alerts.test_relevancia
"""
from alerts.relevancia import (
    _leer_seccion, _clientes_de_fuente, perfil_cliente, historial_entradas,
)


def test_leer_seccion():
    md = "# Titulo\n\n## Temas de interes\nfoo bar\nbaz\n\n## Otra seccion\nignorar esto\n"
    assert _leer_seccion(md, "temas de interes") == "foo bar\nbaz"
    assert _leer_seccion(md, "no existe") == ""


def test_clientes_de_fuente():
    assert _clientes_de_fuente("bayer|syngenta", "bayer") is True
    assert _clientes_de_fuente("bayer|syngenta", "google") is False
    assert _clientes_de_fuente("todos", "cualquiera") is True
    assert _clientes_de_fuente(None, "bayer") is False
    assert _clientes_de_fuente("", "bayer") is False


def test_perfiles_reales_no_vacios():
    # Los 4 clientes reales deben tener perfil en prosa (Temas de interes o
    # Perfil para prompts) - si esto da vacio, el matching NL para ese
    # cliente queda ciego sin que nadie lo note.
    for slug in ("google", "incode", "bayer", "syngenta"):
        perfil = perfil_cliente(slug)
        assert len(perfil) > 100, f"perfil vacio/muy corto para {slug}"


def test_historial_google_vacio_no_fabricado():
    # Google no tiene entradas reales todavia (ver clientes/google/historial_alertas.md)
    # - confirmar que el parser no inventa una entrada de la nota "sin entradas".
    assert historial_entradas("google") == []


def test_historial_bayer_tiene_entradas_reales():
    entradas = historial_entradas("bayer")
    assert len(entradas) >= 1
    assert any("Minsa" in e["cuerpo"] or "DIGEMID" in e["cuerpo"] for e in entradas)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
