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


def test_similitudes_noticias_separa_normas_distintas():
    import numpy as np
    from noticias.historias import UMBRAL_NOTICIAS, similitudes_noticias
    v = lambda *x: np.array(x, "float32") / np.linalg.norm(x)
    titulos = ["JNE reporta 83 amenazas", "JNE alertó sobre 83 amenazas", "Sin vector",
               "DECRETO SUPREMO N° 200-2026-EF", "201-2026-EF — Decreto Supremo"]
    vecs = [v(1, 0, 0), v(.97, .2, 0), None, v(0, 0, 1), v(0, .05, 1)]
    sims = similitudes_noticias(vecs, titulos)
    assert agrupar(titulos, sims=sims, umbral=UMBRAL_NOTICIAS) == [0, 0, 1, 2, 3]
    titulos[4] = "200-2026-EF — Decreto Supremo que autoriza"
    assert agrupar(titulos, sims=similitudes_noticias(vecs, titulos), umbral=UMBRAL_NOTICIAS)[3:] == [2, 2]
    # Mismo portal: no se junta (plantillas como el clima por ciudad).
    fuentes = ["Gestion", "Gestion", "X", "El Peruano", "MEF"]
    assert agrupar(titulos, sims=similitudes_noticias(vecs, titulos, fuentes), umbral=UMBRAL_NOTICIAS)[:2] == [0, 1]
