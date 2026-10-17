import sqlite3
from datetime import datetime, timezone

from noticias.digest import (MENSAJE_MAX_CHARS, _formatear_grupo, _formatear_match_pl,
                             _guardar_ultimo_id, _noticias_desde, armar_grupos,
                             formatear_mensajes, init_schema, run)


def test_agrupa_y_no_repite():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
    conn.execute("INSERT INTO noticias_fuentes VALUES (1,'PE','Medio A','Coyuntura Politica',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (2,'PE','Medio B','Coyuntura Politica',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (3,'PE','Blog de cocina','Temas Salud',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (4,'PE','MINSA','Temas Salud',1)")
    filas = [
        # Mismo evento (ratificacion de Velarde) contado por dos medios.
        (1, 1, "Pleno del Senado aprueba ratificación de Julio Velarde como presidente del BCRP", "http://a/1", None),
        (2, 2, "Julio Velarde es ratificado como presidente del BCR por el Pleno del Senado", "http://a/2", None),
        (3, 3, "Receta de ceviche para el verano", "http://a/3", None),
        # Relleno: con un corpus de solo 2 documentos relevantes el TF-IDF
        # no discrimina bien (cada palabra aparece en 1 de 2 docs, IDF
        # degenerado - mismo problema real que en noticias/avances_ec.py).
        # Con mas notas de vocabulario distinto, "Velarde"/"BCRP"/"Senado"
        # (compartidas) pesan menos que las palabras propias de cada nota -
        # igual que se verifico en vivo contra el corpus real de produccion.
        (4, 1, "Ejecutivo presenta proyecto de ley de reforma tributaria", "http://a/4", None),
        (5, 2, "El presidente del Consejo de Ministros anuncia nuevo gabinete", "http://a/5", None),
        (6, 1, "La presidenta encabeza ceremonia por el Día de la Bandera", "http://a/6", None),
        (7, 2, "El ministro de Economía presenta el presupuesto 2027 al Congreso", "http://a/7", None),
        # Tramite interno que menciona "Decreto Legislativo": tags='normas' lo saca.
        (8, 4, "CONCEDER licencia sin goce de haber a la servidora bajo el "
               "Decreto Legislativo N° 1057, como Asistente Administrativa",
         "http://a/8", "normas"),
        # Salud generica que co-tagea Coyuntura política por "ministro".
        (9, 4, "Ministro de Salud anuncia nueva campaña de vacunación contra el sarampión",
         "http://a/9", None),
        # Resolucion de El Peruano: tags pipe-joined con 'normativa'.
        (10, 1, "JURADO NACIONAL DE ELECCIONES — RESOLUCIÓN N° 3255-2026-JNE: "
                "Confirman la Resolución Nº 00424-2026-JEE-HYLS/JNE",
         "http://a/10", "Coyuntura política|el-peruano|normativa"),
        # Presidente de un club de futbol.
        (11, 1, "Miguel Montalvo, presidente de Barcelona SC, evalúa el "
                "cambio del club a sociedad anónima", "http://a/11", None),
    ]
    conn.executemany("INSERT INTO noticias (id, fuente_id, titulo, resumen, url, tags) "
                     "VALUES (?, ?, ?, NULL, ?, ?)", filas)

    grupos, ultimo = armar_grupos(conn, "PE")
    assert ultimo == 11, ultimo
    assert not any(n["id"] == 8 for g in grupos for n in g), \
        "el item tags='normas' no deberia colarse pese a clasificar como Coyuntura política"
    assert not any(n["id"] == 9 for g in grupos for n in g), \
        "una noticia de Salud/Crop generica no debe colar solo por co-tagear Coyuntura política"
    assert not any(n["id"] == 11 for g in grupos for n in g), \
        "un presidente de club de futbol no debe colar como Coyuntura política"
    assert not any(n["id"] == 10 for g in grupos for n in g), \
        "una resolucion administrativa de El Peruano (tags pipe-joined con "\
        "'normativa') no deberia colarse"
    # Las 2 notas sobre Velarde se agrupan en 1; el resto (relleno + receta,
    # que no es relevante) quedan como grupos propios de 1 sola nota.
    grupo_velarde = next(g for g in grupos if len(g) > 1)
    assert len(grupo_velarde) == 2, grupo_velarde
    assert {n["id"] for n in grupo_velarde} == {1, 2}
    grupos = [grupo_velarde] + [g for g in grupos if g is not grupo_velarde]

    mensajes = formatear_mensajes(grupos, [])
    assert len(mensajes) == 1
    msg = mensajes[0]
    assert "*PERÚ*" in msg and "*ECUADOR*" not in msg
    assert "Pleno del Senado aprueba ratificación de Julio Velarde" in msg
    assert "Medio B" in msg  # la fuente adicional queda anotada

    # Sin nada relevante -> sin mensajes, no se manda nada.
    assert formatear_mensajes([], []) == []

    # El estado avanza y no re-trae lo ya visto.
    _guardar_ultimo_id(conn, "PE", ultimo)
    grupos2, ultimo2 = armar_grupos(conn, "PE")
    assert grupos2 == [] and ultimo2 == ultimo



def test_matches_pl_ec():
    """Una noticia del INIAP matchea el PL trackeado aunque no sea Coyuntura
    política, y sale en su propia seccion."""
    from unittest.mock import patch

    import noticias.digest as dg

    trackeados = [{"pl_numero": "473129", "titulo_matriz":
                   "Proyecto de ley reformatoria a la Ley Constitutiva del INIAP",
                   "clientes": ["bayer", "syngenta"]}]
    vistas = [
        {"id": 1, "titulo": "ECUADOR: Comisión aprueba informe para reformar la Ley del INIAP",
         "resumen": None, "url": "http://x/1", "fuente": "Medio X", "tags": None},
        # Otro medio sobre el MISMO PL: se agrupa con el primero.
        {"id": 2, "titulo": "Pleno tramitó en primer debate la normativa para modernizar el INIAP",
         "resumen": None, "url": "http://x/2", "fuente": "Medio Z", "tags": None},
        {"id": 3, "titulo": "Presidenta Fujimori entrega ayuda humanitaria a población de Purús",
         "resumen": None, "url": "http://x/3", "fuente": "Medio Y", "tags": None},
    ]
    with patch("clientes.matrices.pls_trackeados_ec", lambda: trackeados):
        matches = dg._matches_pl_ec(vistas)
    assert len(matches) == 1, matches  # los 2 articulos de INIAP se agrupan en 1
    assert matches[0]["id"] == 1, matches  # se queda con el primero visto como representante
    assert matches[0]["n_articulos"] == 2, matches
    assert matches[0]["pl_titulo"] == trackeados[0]["titulo_matriz"]

    mensajes = dg.formatear_mensajes([], [], matches)
    assert len(mensajes) == 1
    msg = mensajes[0]
    assert "*PL DE INTERÉS (ECUADOR)*" in msg
    assert "INIAP" in msg
    assert "+1 más" in msg
    assert "bayer/syngenta" in msg

    # Sin matches, esta seccion no aparece (y sin nada mas, sin mensajes).
    assert dg.formatear_mensajes([], [], []) == []


def test_pais_multipais():
    """Las fuentes multipais se reclasifican por contenido: una nota peruana
    de 'DPL News Ecuador' va al stream de PE."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
    conn.execute("INSERT INTO noticias_fuentes VALUES (1,'EC','DPL News Ecuador','Temas KYC/AML',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (2,'EC','El Universo','Coyuntura Politica',1)")
    filas = [
        # Real (titulo real, DPL News Ecuador, catalogada pais='EC') - debe
        # aparecer en el stream de PE, no en el de EC.
        (1, 1, "Rafael Rey deja el Ministerio de Transportes y Comunicaciones de Perú", None, "http://a/1", None),
        # Real de Ecuador, misma fuente multi-pais - debe seguir en EC.
        (2, 1, "Ecuador: Fiscalía pidió vincular a la esposa de Aquiles Álvarez al caso Goleada", None, "http://a/2", None),
        # Fuente normal (no multi-pais), sin cambios de comportamiento.
        (3, 2, "Daniel Noboa llega a Estados Unidos para participar en la Asamblea General de la ONU", None, "http://a/3", None),
    ]
    conn.executemany("INSERT INTO noticias (id, fuente_id, titulo, resumen, url, tags) "
                     "VALUES (?, ?, ?, ?, ?, ?)", filas)

    vistas_pe = _noticias_desde(conn, "PE", 0)
    vistas_ec = _noticias_desde(conn, "EC", 0)
    assert {n["id"] for n in vistas_pe} == {1}, vistas_pe
    assert {n["id"] for n in vistas_ec} == {2, 3}, vistas_ec


def test_run_no_manda_nada_sin_novedades():
    """Sin nada relevante, run() no manda ningun WhatsApp (mismo criterio
    que el correo)."""
    from unittest.mock import patch

    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
    enviados = []
    with patch("congreso_live.notify.enviar_whatsapp", lambda msg: enviados.append(msg) or True), \
         patch("clientes.matrices.pls_trackeados_ec", lambda: []):
        run(conn)
    assert enviados == [], "sin nada relevante no se manda nada"


def test_formatear_grupo_acorta_urls_largas():
    """Las URLs largas (Google News) se acortan via congreso_live.notify."""
    from unittest.mock import patch

    larga = "https://news.google.com/rss/articles/" + "A" * 500
    with patch("congreso_live.notify.acortar_url", lambda u: "https://tinyurl.com/xyz"):
        linea = _formatear_grupo([{"titulo": "Un titulo", "fuente": "Medio",
                                    "url": larga}])
        assert "https://tinyurl.com/xyz" in linea
        assert larga not in linea

        linea_pl = _formatear_match_pl({"titulo": "Nota", "pl_titulo": "PL X",
                                         "url": larga, "clientes": ["bayer"]})
        assert "https://tinyurl.com/xyz" in linea_pl
        assert larga not in linea_pl


def test_formatear_mensajes_parte_en_varios():
    """Un backlog grande se reparte en varios mensajes numerados, sin perder
    ninguna noticia."""
    grupos_ec = [
        [{"titulo": f"Noticia de prueba numero {i} con un titulo bastante "
                    "largo para simular contenido real de produccion",
          "fuente": "Medio X", "url": f"http://x/{i}"}]
        for i in range(30)
    ]
    mensajes = formatear_mensajes([], grupos_ec)
    assert len(mensajes) > 1, "un backlog grande debe partirse en varios mensajes"
    for i, m in enumerate(mensajes, 1):
        assert len(m) <= MENSAJE_MAX_CHARS + 150, \
            f"mensaje {i} se fue muy por encima del limite: {len(m)} chars"
        assert f"({i}/{len(mensajes)})" in m
    # Ninguna noticia se pierde - los 30 titulos aparecen en algun mensaje.
    todo = "\n".join(mensajes)
    for i in range(30):
        assert f"Noticia de prueba numero {i} " in todo, f"se perdio la noticia {i}"


def test_ignora_noticias_viejas():
    """Lo de fecha_pub vieja no pasa aunque sea nuevo en la DB (las busquedas
    de Google News no son cronologicas); sin fecha_pub cuenta como reciente."""
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
    conn.execute("INSERT INTO noticias_fuentes VALUES (1,'EC','Google News EC','Coyuntura Politica',1)")
    filas = [
        # Articulo de 2017 que una busqueda de Google News trae hoy.
        (1, 1, "El Congreso de Ecuador debate el caso Odebrecht en sesion plenaria",
         None, "http://x/1", None, "2017-09-05T07:00:00Z"),
        # Contraste: mismo tema, pero realmente de hoy - debe pasar.
        (2, 1, "El Congreso aprueba en el Pleno la nueva ley de emergencia",
         None, "http://x/2", None, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        # Sin fecha_pub (NULL) - se trata como reciente (mismo criterio
        # que el resto del codigo, COALESCE con first_seen_at).
        (3, 1, "El presidente encabeza reunion de gabinete en el Congreso",
         None, "http://x/3", None, None),
    ]
    conn.executemany("INSERT INTO noticias (id, fuente_id, titulo, resumen, url, tags, fecha_pub) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", filas)

    grupos, ultimo = armar_grupos(conn, "EC")
    assert ultimo == 3, ultimo
    ids_incluidos = {n["id"] for g in grupos for n in g}
    assert 1 not in ids_incluidos, "un articulo de 2017 no debe colar como noticia de hoy"
    assert 2 in ids_incluidos, "una noticia real de hoy si debe pasar"
    assert 3 in ids_incluidos, "sin fecha_pub se trata como reciente, no se excluye"
