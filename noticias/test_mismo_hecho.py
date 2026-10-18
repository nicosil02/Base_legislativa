import json

from noticias import mismo_hecho as mh


def test_texto_limpia_html_y_no_repite_titulo():
    assert mh.texto("Blanca López renuncia", "<p>Blanca López renuncia al Concejo</p>") == "Blanca López renuncia"
    assert mh.texto("Título &amp; algo", "Otro&nbsp;texto") == "Título & algo. Otro texto"


def test_juzgar_gemini_por_lotes():
    pares = [{"ta": f"a{i}", "tb": f"b{i}"} for i in range(35)]
    llamadas = []

    def falso(prompt, system, modelo, schema):
        llamadas.append(prompt)
        n = prompt.count("\nA: ")
        return json.dumps([{"indice": i, "mismo": i % 2 == 0} for i in range(1, n + 1) if i != 3])

    v = mh.juzgar_gemini(pares, generar=falso)
    assert len(llamadas) == 2 and len(v) == 35
    assert v[:4] == [False, True, None, True] and v[30] is False


def test_metricas():
    assert mh._metricas([1, 1, 0, 0], [1, 0, 1, 0]) == {"precision": 0.5, "recall": 0.5, "f1": 0.5, "exactitud": 0.5}


def test_importar_humanos_le_gana_al_modelo(tmp_path, monkeypatch):
    import json
    import sqlite3
    from noticias import mismo_hecho as mh
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "noticias_combinadas.json").write_text(json.dumps([{"ids": [9, 3, 5]}]))
    monkeypatch.setattr(mh, "ROOT", tmp_path)
    c = sqlite3.connect(":memory:")
    mh.asegurar_tabla(c)
    c.execute("INSERT INTO mismo_hecho VALUES (3, 5, 0, 'modelo', 0.1, 0.8, 'x')")
    assert mh.importar_humanos(c) == 3
    assert c.execute("SELECT igual, juez FROM mismo_hecho WHERE a=3 AND b=5").fetchone() == (1, "humano")
