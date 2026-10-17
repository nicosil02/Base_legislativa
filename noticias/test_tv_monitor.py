import sqlite3
from pathlib import Path

from core.text import norm
from noticias.tv_monitor import (EN_VIVO, NO_NOTICIAS, SCHEMA, buscar_menciones, guardar_tramo,
                                 mensaje_aviso, parse_json3, terminos_de, vale_aviso)


def test_guardar_tramo_y_aviso(tmp_path: Path):
    c = sqlite3.connect(str(tmp_path / "t.db"))
    for s in SCHEMA:
        c.execute(s)
    vivo = {"id": "LIVE1", "titulo": "RPP en vivo", "inicio": 0}
    assert guardar_tramo(c, "PE", "RPP Noticias", vivo, [(10, "hola")]) == []
    ms = guardar_tramo(c, "PE", "RPP Noticias", vivo, [(70, "el ministro Vinelli y el Senasa")])
    assert len(ms) == 1 and vale_aviso(ms[0]["terminos"])  # Senasa = tema de cliente
    r = {"relevante": True, "quien": "Marco Vinelli, ministro de Agricultura",
         "que": "Anunció cambios en el Senasa.", "por_que": "Toca a Bayer y Syngenta."}
    txt = mensaje_aviso("RPP Noticias", vivo, ms[0], r)
    assert txt.startswith("📺 RPP Noticias en vivo") and "Marco Vinelli" in txt
    assert not vale_aviso(["fenomeno del nino", "Keiko Fujimori"])  # general: queda en la app
    assert not vale_aviso(["César Astudillo"])  # ministro solo: queda en la app
    assert c.execute("SELECT texto, n_menciones FROM tv_vistos").fetchone() == (
        "hola el ministro Vinelli y el Senasa", 1)
    c.close()


def test_menciones():
    assert buscar_menciones([(0, "el ministro Vineli dijo")])[0]["terminos"] == ["Marco Vinelli"]
    assert terminos_de("el presidente Novoa") == ["Daniel Noboa"]
    # Publicidad repetida en el programa: una sola mencion.
    promo = "no vea el acto si quiere ver candidatos abusar de la inteligencia artificial de una manera ridicula"
    assert len(buscar_menciones([(0, promo), (300, promo), (600, promo)])) == 1
    assert not buscar_menciones([(0, "maquillaje hecho con semillas y flores")])
    lineas = [(0, "buenas noches"), (10, "hoy nos acompaña el ministro Vinelli"),
              (20, "hablamos de las facultades legislativas"), (200, "pasamos a deportes"),
              (400, "el fenómeno El Niño y el Senasa")]
    ms = buscar_menciones(lineas)
    assert len(ms) == 2, ms
    assert ms[0]["terminos"] == ["Marco Vinelli", "facultades legislativas"], ms[0]
    assert "deportes" not in ms[0]["fragmento"]
    assert ms[1]["terminos"] == ["fenomeno el nino", "senasa"], ms[1]
    assert not buscar_menciones([(0, "gol de Cueva en el minuto 90")])
    assert not buscar_menciones([(0, "la presidenta Keiko Fujimori viajo")])  # solo contexto
    assert buscar_menciones([(0, "Keiko Fujimori y el fenomeno El Niño")])
    assert not buscar_menciones([(0, "viajo a Cuba y a Valencia, mas esta diciendo")])
    assert buscar_menciones([(0, "el canciller Espa dijo")])[0]["terminos"] == ["Carlos Espá"]


def test_no_noticias_y_prioridad():
    assert NO_NOTICIAS.search(norm("EXITOSA DEPORTES ⚽ con ÓSCAR PAZ"))
    assert NO_NOTICIAS.search(norm("Willax en vivo - AMOR Y FUEGO - 28/09/2026"))
    assert not NO_NOTICIAS.search(norm("🔴 América Noticias - EN VIVO | 28/09/26"))
    assert EN_VIVO[0][0] == "RPP Noticias" and EN_VIVO[1][0] == "América Noticias"


def test_parse_json3():
    assert parse_json3({"events": [{"tStartMs": 1500, "segs": [{"utf8": "hola "}, {"utf8": "mundo"}]},
                                   {"tStartMs": 2000}]}) == [(1.5, "hola mundo")]
