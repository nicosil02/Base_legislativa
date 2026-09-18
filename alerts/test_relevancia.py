"""Self-check minimo de alerts/relevancia.py (parseo de markdown, sin DB).

Uso: python -m alerts.test_relevancia
"""
from alerts.relevancia import (
    _leer_seccion, _clientes_de_fuente, perfil_cliente, historial_entradas,
    _parsear_veredictos, notas_completas,
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


def test_notas_completas_trae_todo_el_archivo():
    # A diferencia de perfil_cliente() (solo 2 secciones), esto es el
    # notas.md ENTERO - debe incluir secciones que perfil_cliente() no trae,
    # como "Entidades a monitorear".
    completo = notas_completas("bayer")
    assert "Entidades a monitorear" in completo
    assert len(completo) > len(perfil_cliente("bayer"))


def test_parsear_veredictos_formato_esperado():
    respuesta = (
        "1: SI - toca directamente SENASA, que el cliente monitorea\n"
        "2: NO - no tiene relacion con los temas del cliente\n"
        "3: si - variante en minuscula, con guion largo\n"
    )
    v = _parsear_veredictos(respuesta)
    assert v[1] == {"relevante": True, "razon": "toca directamente SENASA, que el cliente monitorea"}
    assert v[2]["relevante"] is False
    assert v[3]["relevante"] is True


def test_parsear_veredictos_ignora_lineas_sin_formato():
    # Respuesta con ruido (encabezados, lineas en blanco) - solo se parsean
    # las lineas con el formato real, sin asumir relevante por defecto.
    respuesta = "Aca va mi analisis:\n\n1: SI - motivo real\nblah blah sin formato\n"
    v = _parsear_veredictos(respuesta)
    assert list(v.keys()) == [1]
    assert v[1]["relevante"] is True


def test_juzgar_relevancia_exige_gemini_api_key():
    import os
    from alerts.relevancia import juzgar_relevancia_llm

    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        try:
            juzgar_relevancia_llm("bayer", [{"tipo": "noticia", "pais": "PE", "titulo": "x",
                                             "resumen": "", "fuente": "f", "fecha": "", "tema": None}])
            raise AssertionError("deberia haber fallado sin GEMINI_API_KEY")
        except RuntimeError as e:
            assert "GEMINI_API_KEY" in str(e), e
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
