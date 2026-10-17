"""Tests de congreso_live/facebook_ec.py (sin red)."""
from congreso_live.facebook_ec import parsear_tarjetas, tipo_de, url_video


def test_parsear_tarjetas_y_urls():
    # Texto real de las tarjetas de la pagina.
    tarjetas = [
        ["111", "EN DIRECTO\nSesión No. 193-2025-2027 Comisión de Desarrollo Económico\n12 espectadores"],
        ["222", "23:20\nSesión Nro. 192-2025-2027 Comisión de Desarrollo Económico\n528 visualizaciones\n · hace 2 días"],
        ["333", "1:09:24\nSESIÓN No. 191-2025-2027 Comisión de Desarrollo Económico\n504 visualizaciones"],
        ["444", "1:46:23\nSesión No. 190-2025-2027 Comisión de Desarrollo Económico\n1,1 mil visualizaciones"],
        ["555", "42:47\nSesión Nro. 189-2025-2027\n678 visualizaciones"],
    ]
    s = parsear_tarjetas(tarjetas, max_n=3)
    assert [x["fb_id"] for x in s] == ["222", "333", "444"]  # salta EN DIRECTO, respeta el tope
    assert s[0]["titulo"].startswith("Sesión Nro. 192")
    assert url_video("fb_222") == "https://www.facebook.com/watch/?v=222"
    assert url_video("ZEUaL91M6D4").startswith("https://www.youtube.com/")
    assert tipo_de("Justicia") == "Comision: Justicia (EC)"
