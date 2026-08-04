"""Catalogo de fuentes de noticias (Peru + Ecuador) con URLs y RSS feeds.

Estructura: lista de dicts con campos:
  categoria, pais, nombre, url, rss_url, tipo, notas

Tipos:
  - rss:    tiene feed RSS estandar (mas comun en medios y WP)
  - html:   solo HTML, requiere scraping con selectores
  - twitter: cuenta X/Twitter, requiere API o scraping (no auto)
  - manual: marcado en el catalogo pero sin scraping automatico

Para agregar/corregir URLs:
  python -m noticias.cli set-rss --pais PE --nombre "Gestion" --rss "https://..."
"""

# ============================================================
# PERU
# ============================================================
FUENTES_PE: list[dict] = [
    # --- COYUNTURA POLITICA: medios principales ---
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "El Comercio",
     "url": "https://elcomercio.pe/politica/",
     "rss_url": "https://elcomercio.pe/feed/", "tipo": "rss", "activa": 0, "notas": "Feed roto - cubierto por Google News"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Gestion",
     "url": "https://gestion.pe/politica/",
     "rss_url": "https://gestion.pe/arcio/rss/category/politica/", "tipo": "rss", "activa": 0, "notas": "Feed roto - cubierto por Google News"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "La Republica",
     "url": "https://larepublica.pe/politica",
     "rss_url": "https://larepublica.pe/feed/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Peru 21",
     "url": "https://peru21.pe/politica/",
     "rss_url": "https://peru21.pe/arcio/rss/category/politica/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "RPP",
     "url": "https://rpp.pe/politica",
     "rss_url": "https://rpp.pe/politica.xml", "tipo": "rss", "activa": 0, "notas": "Feed roto - cubierto por Google News"},

    # --- INSTITUCION: Congreso, ministerios, agencias ---
    {"categoria": "Institucion", "pais": "PE",
     "nombre": "Congreso - Proyectos de Ley",
     "url": "https://wb2server.congreso.gob.pe/spley-portal/",
     "tipo": "html",
     "notas": "Cubierto por modulo scraper/ (API formal)"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "El Peruano",
     "url": "https://elperuano.pe/", "tipo": "html",
     "notas": "Diario oficial; revisar /noticias/ y /normaslegales/"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Canal Congreso",
     "url": "https://canalncongreso.gob.pe/", "tipo": "html"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Agenda del Congreso",
     "url": "https://comunicaciones.congreso.gob.pe/agenda/",
     "rss_url": "https://comunicaciones.congreso.gob.pe/agenda/feed/",
     "tipo": "rss",
     "notas": "Cubierto por modulo mesas_tecnicas/"},
                                        {"categoria": "Institucion", "pais": "PE",
     "nombre": "Direccion de Casinos (Apuestas Deportivas)",
     "url": "https://www.gob.pe/mincetur",
     "tipo": "manual",
     "notas": "Resoluciones de la Direccion General de Juegos de Casino y Maquinas Tragamonedas"},

    # --- TEMAS AGRARIOS ---
                    {"categoria": "Temas Agrarios", "pais": "PE",
     "nombre": "CAP (Convencion Agropecuaria)",
     "url": "https://convencionagropecuaria.com.pe/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CONVEAGRO",
     "url": "https://www.conveagro.org.pe/",
     "rss_url": "https://www.conveagro.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Agraria.pe",
     "url": "https://agraria.pe/",
     "rss_url": "https://agraria.pe/rss", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "AGAP",
     "url": "https://agapperu.org/", "tipo": "html",
     "notas": "Asociacion de Gremios Productores Agrarios del Peru"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CEPES",
     "url": "https://www.cepes.org.pe/",
     "rss_url": "https://www.cepes.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE",
     "nombre": "Sociedad Peruana de Derecho Ambiental",
     "url": "https://spda.org.pe/",
     "rss_url": "https://spda.org.pe/feed/", "tipo": "rss", "activa": 0, "notas": "Feed roto - cubierto por Google News"},

    # --- TEMAS AGRARIOS: portales especializados nuevos ---
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Redagricola",
     "url": "https://redagricola.com/", "rss_url": "https://redagricola.com/feed/",
     "tipo": "rss",
     "notas": "Revista agrocomercial - foco tecnologia y agroexport"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "AgroPeru",
     "url": "https://www.agroperu.pe/",
     "rss_url": "https://www.agroperu.pe/feed/", "tipo": "rss",
     "notas": "Portal agrario general"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Servindi",
     "url": "https://www.servindi.org/",
     "rss_url": "https://www.servindi.org/rss.xml", "tipo": "rss",
     "notas": "Servicios en comunicacion intercultural - foco comunidades y agro rural"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Andina (agencia oficial - agro)",
     "url": "https://andina.pe/agencia/seccion.aspx?codseccion=6",
     "rss_url": "https://andina.pe/agencia/rss.aspx?codseccion=6", "tipo": "rss",
     "notas": "Agencia oficial - seccion agraria (codseccion=6)"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "AgroNoticias Peru",
     "url": "https://agronoticias.pe/",
     "rss_url": "https://agronoticias.pe/feed/", "tipo": "rss",
     "notas": "Portal noticias sector agrario peruano"},

    # --- KYC / AML / Financiero ---
    {"categoria": "Temas KYC/AML", "pais": "PE", "nombre": "SBS - Resoluciones",
     "url": "https://www.sbs.gob.pe/", "tipo": "html",
     "notas": "Superintendencia de Banca, Seguros y AFP - normativa"},
    {"categoria": "Temas KYC/AML", "pais": "PE", "nombre": "Fintech Peru",
     "url": "https://fintechperu.com/",
     "rss_url": "https://fintechperu.com/feed/", "tipo": "rss",
     "notas": "Asociacion Fintech Peru - noticias del sector"},
    {"categoria": "Temas KYC/AML", "pais": "PE",
     "nombre": "Google News PE — SUNAT",
     "url": "https://news.google.com/rss/search?q=SUNAT+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "rss_url": "https://news.google.com/rss/search?q=SUNAT+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "tipo": "rss", "notas": "Query: SUNAT Peru"},
    {"categoria": "Temas KYC/AML", "pais": "PE",
     "nombre": "Google News PE — BCRP",
     "url": "https://news.google.com/rss/search?q=BCRP+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "rss_url": "https://news.google.com/rss/search?q=BCRP+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "tipo": "rss", "notas": "Query: BCRP Peru"},
    {"categoria": "Temas KYC/AML", "pais": "PE",
     "nombre": "Google News PE — UIF lavado",
     "url": "https://news.google.com/rss/search?q=UIF+lavado+activos+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "rss_url": "https://news.google.com/rss/search?q=UIF+lavado+activos+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "tipo": "rss", "notas": "Query: UIF lavado activos Peru"},

    # --- TEMAS SALUD ---
        {"categoria": "Temas Salud", "pais": "PE",
     "nombre": "Ministerio de Salud (estadisticas)",
     "url": "https://www.dge.gob.pe/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "DIGEMID",
     "url": "https://www.gob.pe/digemid", "tipo": "manual", "activa": 0,
     "notas": "Sin listado propio en gob.pe/institucion; cubierto por Google News DIGEMID"},
    {"categoria": "Temas Salud", "pais": "PE",
     "nombre": "Colegio de Quimicos Farmaceuticos del Peru",
     "url": "https://cqfp.pe/",
     "rss_url": "https://cqfp.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Voces Ciudadanas",
     "url": "https://vocesciudadanas.org.pe/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Esperantra",
     "url": "https://esperantra.org/",
     "rss_url": "https://esperantra.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Lazo Rosado",
     "url": "https://lazorosado.org/",
     "rss_url": "https://lazorosado.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE",
     "nombre": "Federacion Peruana de Enfermedades Raras",
     "url": "https://fepper.org.pe/", "tipo": "html"},
    # --- Salud PE: portales nuevos ---
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Diario Medico Peru",
     "url": "https://diariomedico.pe/",
     "rss_url": "https://diariomedico.pe/feed/", "tipo": "rss",
     "notas": "Medio especializado salud/farma"},
    {"categoria": "Temas Salud", "pais": "PE",
     "nombre": "Andina (agencia oficial - salud)",
     "url": "https://andina.pe/agencia/seccion.aspx?codseccion=1",
     "rss_url": "https://andina.pe/agencia/rss.aspx?codseccion=1",
     "tipo": "rss",
     "notas": "Agencia oficial - seccion salud"},

    # --- TEMAS TECH ---
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Niubox Legal",
     "url": "https://niubox.legal/",
     "rss_url": "https://niubox.legal/feed/", "tipo": "rss", "activa": 0, "notas": "Feed roto - cubierto por Google News"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Comex Peru",
     "url": "https://www.comexperu.org.pe/",
     "rss_url": "https://www.comexperu.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "DPL News Peru",
     "url": "https://dplnews.com/",
     "rss_url": "https://dplnews.com/feed/", "tipo": "rss",
     "notas": "Filtrar por etiqueta Peru en el feed"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Hiperderecho",
     "url": "https://hiperderecho.org/",
     "rss_url": "https://hiperderecho.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Bloomberg en Linea",
     "url": "https://www.bloomberglinea.com/",
     "rss_url": "https://www.bloomberglinea.com/arc/outboundfeeds/rss/?outputType=xml",
     "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "PE",
     "nombre": "Asociacion Latinoamericana de Internet",
     "url": "https://alai.lat/",
     "rss_url": "https://alai.lat/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Ebiz Latam",
     "url": "https://ebizlatam.com/",
     "rss_url": "https://ebizlatam.com/feed/", "tipo": "rss"},
]


# ============================================================
# ECUADOR
# ============================================================
FUENTES_EC: list[dict] = [
    # --- COYUNTURA POLITICA ---
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "El Comercio",
     "url": "https://www.elcomercio.com/actualidad/",
     "rss_url": "https://www.elcomercio.com/feed/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "El Universo",
     "url": "https://www.eluniverso.com/noticias/politica/",
     "rss_url": "https://www.eluniverso.com/rss/politica/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "PRIMICIAS",
     "url": "https://www.primicias.ec/politica/",
     "rss_url": "https://www.primicias.ec/rss/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Gestion",
     "url": "https://www.revistagestion.ec/", "tipo": "html"},
    {"categoria": "Coyuntura Politica", "pais": "EC",
     "nombre": "Bloomberg Linea Ecuador",
     "url": "https://www.bloomberglinea.com/ecuador/",
     "rss_url": "https://www.bloomberglinea.com/arc/outboundfeeds/rss/?outputType=xml",
     "tipo": "rss"},

    # --- INSTITUCION ---
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Asamblea Nacional - Proyectos de Ley",
     "url": "https://proyectosdeley.asambleanacional.gob.ec/",
     "tipo": "html",
     "notas": "Cubierto por modulo scraper_ec/"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Registro Oficial",
     "url": "https://www.registroficial.gob.ec/", "tipo": "html"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Decretos Presidenciales",
     "url": "https://www.presidencia.gob.ec/decretos/", "tipo": "html"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Portal de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/",
     "rss_url": "https://www.asambleanacional.gob.ec/es/noticias/feed",
     "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Agenda de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/es/agenda_de_comunicacion",
     "tipo": "html",
     "notas": "Cubierto por modulo agenda_ec/"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Ministerio de Economia y Finanzas",
     "url": "https://www.finanzas.gob.ec/", "tipo": "html"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Ministerio de Relaciones Exteriores y Movilidad Humana",
     "url": "https://www.cancilleria.gob.ec/", "tipo": "html"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "ARCSA (Regulacion Sanitaria)",
     "url": "https://www.controlsanitario.gob.ec/", "tipo": "html"},

    # --- TEMAS AGRARIOS ---
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Resoluciones Ministerio de Agricultura",
     "url": "https://www.agricultura.gob.ec/normativa/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio de Agricultura y Ganaderia",
     "url": "https://www.agricultura.gob.ec/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio del Ambiente",
     "url": "https://www.ambiente.gob.ec/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio de Produccion Comercio Exterior",
     "url": "https://www.produccion.gob.ec/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Agencia de Regulacion y Control Fito y Zoosanitario",
     "url": "https://www.agrocalidad.gob.ec/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "Agrocalidad Noticias",
     "url": "https://www.agrocalidad.gob.ec/noticias/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "CONAIE (Confederacion Indigenas)",
     "url": "https://conaie.org/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "El Productor",
     "url": "https://elproductor.com/",
     "rss_url": "https://elproductor.com/feed/", "tipo": "rss",
     "notas": "Cloudflare bypass via cloudscraper (en scraper.py)"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Observatorio de Cambio Rural",
     "url": "https://ocaru.org.ec/",
     "rss_url": "https://ocaru.org.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "La Revista Agraria (LRA)",
     "url": "https://larevistaagraria.org/",
     "rss_url": "https://larevistaagraria.org/feed/", "tipo": "rss",
     "notas": "Publicacion academica - analisis sector agrario andino"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "Mundo Agropecuario",
     "url": "https://mundoagropecuario.com/",
     "rss_url": "https://mundoagropecuario.com/feed/", "tipo": "rss",
     "notas": "Portal agrario regional"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "INIAP",
     "url": "https://www.iniap.gob.ec/", "tipo": "html"},

    # --- KYC / AML ---
    {"categoria": "Temas KYC/AML", "pais": "EC",
     "nombre": "Ministerio de Telecomunicaciones",
     "url": "https://www.telecomunicaciones.gob.ec/", "tipo": "html"},
    {"categoria": "Temas KYC/AML", "pais": "EC",
     "nombre": "Superintendencia de Proteccion de Datos Personales",
     "url": "https://www.proteccionderechos.gob.ec/", "tipo": "html"},
    {"categoria": "Temas KYC/AML", "pais": "EC", "nombre": "DPL News Ecuador",
     "url": "https://dplnews.com/",
     "rss_url": "https://dplnews.com/feed/", "tipo": "rss"},

    # --- TEMAS SALUD ---
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Proyectos normativos ARCSA",
     "url": "https://www.controlsanitario.gob.ec/proyectos-normativos/",
     "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "EC",
     "nombre": "Ministerio de Salud Publica",
     "url": "https://www.salud.gob.ec/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "IESS (Seg. Social)",
     "url": "https://www.iess.gob.ec/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "ALAFAR Ecuador",
     "url": "https://www.alafar.org/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "SOLCA Ecuador",
     "url": "https://www.solca.med.ec/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "EC",
     "nombre": "Jovenes Contra el Cancer Ecuador",
     "url": "https://jovenescontraelcancerec.org/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Pacientes Ecuador",
     "url": "https://pacientesecuador.org/", "tipo": "html"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Edicion Medica",
     "url": "https://www.edicionmedica.ec/",
     "rss_url": "https://www.edicionmedica.ec/rss", "tipo": "rss"},

    # --- TEMAS TECH ---
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Criptonoticias",
     "url": "https://www.criptonoticias.com/",
     "rss_url": "https://www.criptonoticias.com/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "EC",
     "nombre": "Camara Ecuatoriana de Comercio Exterior",
     "url": "https://www.cce.org.ec/", "tipo": "html"},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Forbes Digital Ecuador",
     "url": "https://www.forbes.com.ec/",
     "rss_url": "https://www.forbes.com.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "DPL Tech Ecuador",
     "url": "https://dplnews.com/", "tipo": "rss",
     "rss_url": "https://dplnews.com/feed/"},
    {"categoria": "Temas Tech", "pais": "EC",
     "nombre": "Camara de Innovacion y Tecnologia Ecuatoriana",
     "url": "https://www.cite.org.ec/", "tipo": "html"},
]


# ============================================================
# GOOGLE NEWS RSS por keyword (cobertura mediatica automatica)
# ============================================================
# Google News expone busquedas como RSS: cero API key, ~100 items/query,
# ordenado por relevancia+fecha, incluye todos los medios que indexa.
# Reemplaza el 80% de la agenda mediatica sin depender de feeds propios rotos.
#
# Doc: https://news.google.com/rss/search?q=<query>&hl=<lang>&gl=<pais>&ceid=<pais>:<lang>
# Cada entrada aca genera una "fuente" que se scrapea como RSS normal.

_GN_LANG = "es-419"

def _gn(pais: str, categoria: str, nombre: str, query: str) -> dict:
    """Genera un dict fuente para Google News RSS."""
    gl = pais  # PE, EC, CO, AR, CL, UY
    ceid = f"{pais}:es"
    url = (f"https://news.google.com/rss/search?q={query}"
           f"&hl={_GN_LANG}&gl={gl}&ceid={ceid}")
    return {
        "categoria": categoria,
        "pais": pais,
        "nombre": f"Google News {pais} — {nombre}",
        "url": url,
        "rss_url": url,
        "tipo": "rss",
        "notas": f"Query: {query}",
    }


FUENTES_GOOGLE_NEWS: list[dict] = [
    # --- SALUD / FARMA (Bayer Farma, Gilead) ---
    _gn("PE", "Salud", "DIGEMID", "DIGEMID+medicamentos"),
    _gn("PE", "Salud", "MINSA reforma", "MINSA+reforma+salud"),
    _gn("PE", "Salud", "Alto costo", "medicamentos+alto+costo+Peru"),
    _gn("PE", "Salud", "PNUME", "Petitorio+Nacional+Unico+Medicamentos"),
    _gn("PE", "Salud", "Cancer", "Ley+Nacional+del+Cancer+Peru"),
    _gn("EC", "Salud", "ARCSA", "ARCSA+medicamentos"),
    _gn("EC", "Salud", "MSP", "Ministerio+Salud+Publica+Ecuador+reforma"),
    _gn("EC", "Salud", "IESS medicamentos", "IESS+medicamentos+desabastecimiento"),
    # Cono Sur (Gilead)

    # --- AGRO (Bayer Crop, Syngenta) ---
    _gn("PE", "Agro", "SENASA", "SENASA+plaguicidas"),
    _gn("PE", "Agro", "Moratoria OVM", "moratoria+transgenicos+Peru"),
    _gn("PE", "Agro", "Glifosato", "glifosato+Peru+prohibicion"),
    _gn("PE", "Agro", "Agroecologia", "Ley+agroecologia+Peru"),
    _gn("PE", "Agro", "Fusarium banano", "Fusarium+R4T+banano"),
    _gn("PE", "Agro", "Semillas", "semillas+nativas+certificadas+Peru"),
    _gn("EC", "Agro", "Agrocalidad", "Agrocalidad+plaguicidas"),
    _gn("EC", "Agro", "MAG plaguicidas", "MAG+Ecuador+plaguicidas"),
    _gn("EC", "Agro", "Bioinsumos", "bioinsumos+Ecuador+agroecologia"),

    # --- DIGITAL / TECH (Google, Niubox, INCODE) ---
    _gn("PE", "Digital", "Datos personales", "Ley+29733+proteccion+datos"),
    _gn("PE", "Digital", "IA Ley 31814", "Ley+31814+inteligencia+artificial"),
    _gn("PE", "Digital", "ANPD", "ANPD+Peru+proteccion+datos"),
    _gn("PE", "Digital", "Ciberseguridad", "ciberseguridad+Peru+ley"),
    _gn("PE", "Digital", "Menores digitales", "verificacion+edad+menores+plataformas+Peru"),
    _gn("PE", "Digital", "OSIPTEL plataformas", "OSIPTEL+plataformas+digitales"),
    _gn("PE", "Digital", "OCDE Peru", "adhesion+OCDE+Peru+digital"),
    _gn("EC", "Digital", "MINTEL datos", "MINTEL+Ecuador+proteccion+datos"),
    _gn("EC", "Digital", "IA Ecuador", "inteligencia+artificial+Ecuador+ley"),
    # INCODE regional (LATAM identity)
    _gn("PE", "Digital", "KYC LAFT", "KYC+lavado+activos+Peru"),
    _gn("PE", "Digital", "Registro SIM", "registro+chips+SIM+Peru"),

    # --- FINANCIERO / FINTECH ---
    _gn("PE", "Financiero", "SBS fintech", "SBS+fintech+Peru"),
    _gn("PE", "Financiero", "Finanzas abiertas", "finanzas+abiertas+Peru+open+finance"),
]


def all_fuentes() -> list[dict]:
    return FUENTES_PE + FUENTES_EC + FUENTES_GOOGLE_NEWS
