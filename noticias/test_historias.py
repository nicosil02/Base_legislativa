from noticias.historias import _claves_busqueda, agrupar, ya_avisado


def test_agrupa_por_similitud():
    import numpy as np
    sims = np.array([[1, .9, .1], [.9, 1, .2], [.1, .2, 1]])
    assert agrupar(["a", "b", "c"], sims=sims, umbral=0.78) == [0, 0, 1]
    assert agrupar([]) == []


def test_ya_avisado():
    assert ya_avisado("El gobierno sube el sueldo minimo a 1230 soles desde octubre",
                      ["Gobierno anuncia que el sueldo minimo sube a 1230 soles desde octubre"])
    assert not ya_avisado("Senasa aprueba requisitos para importar semillas",
                          ["Gobierno anuncia que el sueldo minimo sube a 1230 soles"])


def test_claves_busqueda_sin_relleno():
    claves = _claves_busqueda("Vinelli anunció que el Senasa prohibirá tres plaguicidas "
                              "y señaló que resolvió hacerlo desde noviembre")
    assert claves[:1] == ["Senasa"]
    assert "señaló" not in claves and "resolvió" not in claves
    assert len(claves) <= 5
