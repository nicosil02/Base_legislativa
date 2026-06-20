"""Checks minimos de la logica nueva (gob.pe + RSS). Correr: python -m noticias.test_scraper"""
from noticias import scraper as S


def test_slug():
    assert S._gobpe_slug("https://www.gob.pe/institucion/minsa/noticias") == "minsa"
    assert S._gobpe_slug("https://www.gob.pe/midagri") == "midagri"
    assert S._gobpe_slug("https://elcomercio.pe/") is None
    assert S._gobpe_slug(None) is None


def test_fecha():
    assert S._parse_gobpe_date(" 2 de diciembre de 2024 -  6:29 p. m.") == "2024-12-02T00:00:00Z"
    assert S._parse_gobpe_date("15 de enero de 2026") == "2026-01-15T00:00:00Z"
    assert S._parse_gobpe_date("sin fecha") is None
    assert S._parse_gobpe_date(None) is None


def test_gobpe_parse_offline():
    """fetch_gobpe sobre una sesion fake: parsea results del JSON gob.pe."""
    sample = {"data": {"attributes": {"results": [
        {"name_with_parent": "MINSA aprueba nueva norma de medicamentos",
         "publication": " 3 de marzo de 2026 -  9:00 a. m.",
         "content": "Resumen de la noticia",
         "url": '<a href="/institucion/minsa/noticias/123-titulo">x</a>'},
        {"name_with_parent": "", "url": '<a href="/x">y</a>'},  # sin titulo -> descartado
    ]}}}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return sample

    class FakeSession:
        def get(self, *a, **k): return FakeResp()

    items = S.fetch_gobpe(
        {"url": "https://www.gob.pe/institucion/minsa/noticias",
         "categoria": "Temas Salud"},  # salud -> pide noticias + normas (2 pasadas)
        FakeSession())
    # 2 pasadas (noticias+normas) x 1 item valido cada una = 2
    assert len(items) == 2, items
    it = items[0]
    assert it["url"] == "https://www.gob.pe/institucion/minsa/noticias/123-titulo"
    assert it["titulo"].startswith("MINSA aprueba")
    assert it["fecha_pub"] == "2026-03-03T00:00:00Z"
    assert it["tags"] in ("noticias", "normas")


def test_solo_noticias_si_no_es_regulador():
    """Categoria sin salud/agro/kyc -> solo 1 pasada (noticias)."""
    sample = {"data": {"attributes": {"results": [
        {"name_with_parent": "t", "url": '<a href="/institucion/pcm/noticias/1-x">x</a>',
         "publication": "1 de enero de 2026"}]}}}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return sample
    class Sx:
        def get(self, *a, **k): return R()

    items = S.fetch_gobpe(
        {"url": "https://www.gob.pe/institucion/pcm/noticias", "categoria": "Institucion"}, Sx())
    assert len(items) == 1 and items[0]["tags"] == "noticias", items


def test_normas_titulo_legible():
    """En normas, name_with_parent es solo el codigo -> titulo = codigo + content."""
    sample = {"data": {"attributes": {"results": [
        {"name_with_parent": "0397-2024-MIDAGRI",
         "content": "Autorizar el registro del plaguicida X",
         "publication": "1 de marzo de 2026",
         "url": '<a href="/institucion/midagri/normas/9-x">x</a>'}]}}}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return sample
    class Sx:
        def get(self, *a, **k): return R()

    items = S.fetch_gobpe(
        {"url": "https://www.gob.pe/institucion/midagri/noticias",
         "categoria": "Temas Agrarios"}, Sx())
    # categoria agraria -> 2 pasadas; la de normas debe unir codigo + desc
    norma = [i for i in items if i["tags"] == "normas"][0]
    assert norma["titulo"] == "0397-2024-MIDAGRI — Autorizar el registro del plaguicida X", norma["titulo"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
