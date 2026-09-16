"""Checks de noticias/fuentes.py. Correr: python -m noticias.test_fuentes"""
from noticias.fuentes import all_fuentes


def test_nitter_desactivadas():
    # Bug real 2026-09-16: las fuentes "X - ..." (cuentas de X/Twitter)
    # dependen de nitter.net para tener RSS - nitter.net dejo de responder
    # (verificado en vivo, HTTP 000) y ninguna trajo jamas una noticia real
    # (verificado contra la DB de produccion). Se desactivan todas de una
    # sola vez en all_fuentes(), sin tocar cada dict literal.
    fs = all_fuentes()
    nitter = [f for f in fs if "nitter.net" in (f.get("rss_url") or "")]
    assert nitter, "esperaba encontrar fuentes con rss_url de nitter.net"
    assert all(f["activa"] == 0 for f in nitter), (
        "todas las fuentes nitter.net deben quedar desactivadas")


def test_primicias_y_registro_oficial_desactivadas():
    # PRIMICIAS: rss_url da 404 real. Registro Oficial (generico html):
    # redundante con el modulo dedicado registro_oficial_ec.py.
    fs = all_fuentes()
    by_name = {f["nombre"]: f for f in fs}
    assert by_name["PRIMICIAS"]["activa"] == 0
    assert by_name["Registro Oficial"]["activa"] == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
