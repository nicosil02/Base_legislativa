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
    # gob.pe escribe "setiembre".
    assert S._parse_gobpe_date("13 de setiembre de 2026 -  7:03 a. m.") == "2026-09-13T00:00:00Z"


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


def test_html_listing_extrae_fecha_del_time_tag():
    """parse_html_listing toma el <time datetime> cercano al titular; si no
    hay, fecha_pub queda None."""
    relleno = "<p>" + ("lorem ipsum texto de relleno para separar items " * 6) + "</p>"
    html = f"""
    <div class="post">
      <time datetime="2026-09-10T14:30:00-05:00">10 de septiembre</time>
      <h2><a href="/noticia-real-de-hoy-con-guiones">Titulo de la noticia real</a></h2>
    </div>
    {relleno}
    <div class="post">
      <h2><a href="/otra-noticia-sin-fecha-cercana">Otro titulo sin fecha</a></h2>
    </div>
    """
    items = S.parse_html_listing(html, "https://ejemplo.pe/")
    con_fecha = next(i for i in items if "noticia-real-de-hoy" in i["url"])
    sin_fecha = next(i for i in items if "otra-noticia" in i["url"])
    assert con_fecha["fecha_pub"] == "2026-09-10T19:30:00Z", con_fecha["fecha_pub"]
    assert sin_fecha["fecha_pub"] is None


def test_backfill_extrae_fecha_de_pagina_real():
    """backfill_fechas saca la fecha del articulo: <time>, meta tags o texto
    de fecha en español (con "setiembre")."""
    html_time = '<html><head></head><body><time datetime="2026-09-05T10:00:00-05:00">x</time></body></html>'
    assert S._extraer_fecha_de_pagina(html_time) == "2026-09-05T15:00:00Z"

    html_meta = '<html><head><meta property="article:published_time" content="2026-09-06T08:00:00-05:00"></head></html>'
    assert S._extraer_fecha_de_pagina(html_meta) == "2026-09-06T13:00:00Z"

    html_texto_es = "<html><body><p>Publicado el 12 de setiembre de 2026 a las 8am</p></body></html>"
    assert S._extraer_fecha_de_pagina(html_texto_es) == "2026-09-12T00:00:00Z"

    assert S._extraer_fecha_de_pagina("<html><body>sin fecha aca</body></html>") is None



class _Resp:
    def __init__(self, data):
        self._d = data
        self.content = __import__("json").dumps(self._d).encode()

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Sesion:
    def __init__(self, data):
        self.data = data

    def get(self, *a, **k):
        return _Resp(self.data)


def test_wpmedia_limpia_titulos():
    from noticias.scraper import fetch_wpmedia
    s = _Sesion([{"date": "2026-10-15T17:14:57", "source_url": "https://x/a.pdf",
                  "title": {"rendered": "23092026_062842_Borrador-Resolucion-Portabilidad"}}])
    it = fetch_wpmedia({"nombre": "SPDP", "url": "https://spdp.gob.ec"}, s, 5)
    assert it[0]["titulo"] == "SPDP: Borrador Resolucion Portabilidad" and "normas" in it[0]["tags"]
