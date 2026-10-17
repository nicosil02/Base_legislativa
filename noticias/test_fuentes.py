from noticias.fuentes import _norm_kw, all_fuentes, matchea_perfil


def test_catalogo_sin_nitter_ni_desactivadas_a_mano():
    # Las fuentes muertas se sacan del catalogo (seed las desactiva en la DB
    # via deactivate_fuentes_huerfanas) en vez de quedar con activa=0.
    fs = all_fuentes()
    assert not [f for f in fs if "nitter.net" in (f.get("rss_url") or "")]
    assert not [f for f in fs if f.get("activa", 1) == 0 and f.get("tipo") != "twitter"]
    assert len({(f["pais"], f["nombre"]) for f in fs}) == len(fs), "nombres duplicados"


def test_primicias_por_google_news_y_registro_oficial_fuera():
    # PRIMICIAS: su RSS da 404, entra por Google News filtrado al dominio.
    # Registro Oficial (html generico) lo cubre registro_oficial_ec.py.
    by_name = {f["nombre"]: f for f in all_fuentes()}
    assert by_name["PRIMICIAS"].get("activa", 1) == 1
    assert "site:primicias.ec" in by_name["PRIMICIAS"]["rss_url"]
    assert "Registro Oficial" not in by_name


def test_cuentas_x_por_google_news():
    by_name = {f["nombre"]: f for f in all_fuentes()}
    keiko = by_name["X - Keiko Fujimori (Presidenta)"]
    assert keiko["activa"] == 1 and keiko["tipo"] == "rss"
    assert "q=%22Keiko+Fujimori%22&hl=es-419&gl=PE" in keiko["rss_url"]
    primicias = by_name["X - Primicias"]  # medio con web propia: no se busca
    assert primicias["activa"] == 0 and primicias["tipo"] == "twitter"


def test_matchea_perfil():
    assert _norm_kw("Ley  Orgánica") == "ley  organica"  # no colapsa espacios
    assert matchea_perfil("bayer", "DIGEMID retira lote", None)
    assert not matchea_perfil("bayer", "Campaña de vacunación escolar", None)
    assert matchea_perfil("cliente-sin-perfil", "lo que sea", None)
