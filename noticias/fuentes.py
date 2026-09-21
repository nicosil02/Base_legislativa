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

Cruce fuente x cliente (ver clientes/_plantillas/matriz_monitoreo/): cada fuente
termina con una lista `clientes` (slugs de clientes/<slug>/, o "todos" para el
backbone legislativo/politico general) resuelta por `_clientes_de()` abajo, sin
tener que anotar cada uno de los ~90 dicts a mano:
  1. INSTITUCION_CLIENTES: lookup exacto por `nombre`, para las ~30 entidades
     de gobierno donde la categoria ("Institucion", o la tematica en la que
     viven MINSA/MEF/etc.) no alcanza para saber a quien le importa. Tags
     copiados de la matriz de monitoreo (ya verificados ahi leyendo cada
     clientes/<cliente>/notas.md real).
  2. CATEGORIA_CLIENTES: fallback por categoria para el resto (medios, gremios,
     cuentas X) - Google/Incode = tech/digital/KYC/AML + coyuntura general;
     Bayer = Salud + Agro + coyuntura; Syngenta = Agro + coyuntura (NO Salud -
     Syngenta es agroquimicos/semillas, no farmaceutica, confirmado en su
     notas.md).
"""

INSTITUCION_CLIENTES: dict[str, list[str]] = {
    # --- PE: backbone legislativo/politico general ---
    "Congreso - Proyectos de Ley": ["todos"],
    "El Peruano": ["todos"],
    "Google News PE — Decreto Supremo": ["todos"],
    "Google News PE — Decreto de Urgencia": ["todos"],
    "Google News PE — Ley promulgada": ["todos"],
    "Google News PE — El Peruano publica": ["todos"],
    "Canal Congreso": ["todos"],
    "Agenda del Congreso": ["todos"],
    "PCM": ["todos"],
    "Presidencia": ["todos"],
    # --- PE: ministerios/agencias con relevancia especifica (matriz 2026-09-12) ---
    "MINSA": ["bayer"],
    "DIGEMID": ["bayer"],
    "Ministerio de Salud (estadisticas)": ["bayer"],
    "MIDAGRI": ["bayer", "syngenta"],
    "SENASA": ["bayer", "syngenta"],
    "MINAM": ["bayer", "syngenta"],
    # MEF: Syngenta (macro/agro) + Google (IVA a plataformas digitales via
    # decreto MEF, explicito en su notas.md). ponytail: MEF publica de todo
    # (presupuesto, transferencias de partidas, macro) - este tag es real
    # pero de alcance angosto (una sola linea de politica digital dentro
    # de todo lo que emite MEF), va a seguir trayendo ruido no-digital para
    # Google hasta que haya un filtro por contenido del articulo, no solo
    # por institucion (auditoria 2026-09-13, confirmado con Nicolas que
    # el ranking por TF-IDF no alcanza para esto).
    "MEF": ["syngenta", "google"],  # ver INSTITUCIONES_AMPLIAS abajo
    "ANPD": ["google", "incode"],
    # RREE: Google Y Incode comparten el mismo eje "relacion EEUU" segun sus
    # notas.md (ambas empresas norteamericanas) - antes solo tenia a Google
    # (auditoria 2026-09-13).
    "RREE": ["google", "incode"],
    "MTC": ["google"],
    "OSIPTEL": ["google"],
    "INDECOPI": ["google", "syngenta"],
    "MINCETUR": ["google", "bayer", "syngenta"],
    "MINEDU": [],
    "PRODUCE": [],
    "Direccion de Casinos (Apuestas Deportivas)": [],
    # --- EC: backbone legislativo/politico general ---
    "Asamblea Nacional - Proyectos de Ley": ["todos"],
    "Registro Oficial": ["todos"],
    "Decretos Presidenciales": ["todos"],
    "Google News EC — Decreto Ejecutivo": ["todos"],
    "Google News EC — Registro Oficial": ["todos"],
    "Google News EC — Ley Orgánica": ["todos"],
    "Portal de la Asamblea Nacional": ["todos"],
    "Agenda de la Asamblea Nacional": ["todos"],
    # --- EC: ministerios/agencias con relevancia especifica ---
    # Ministerio de Economia y Finanzas EC se fusiono en MDEP (Desarrollo
    # Economico y Productivo, junto con Agricultura y Produccion) - la matriz
    # ya tagea MDEP como bayer+syngenta, aplicado aca a las 3 filas viejas
    # que fuentes.py todavia mantiene por separado (mismo dominio nuevo).
    "Ministerio de Economia y Finanzas": ["bayer", "syngenta"],
    "Ministerio de Agricultura y Ganaderia": ["bayer", "syngenta"],
    "Resoluciones Ministerio de Agricultura": ["bayer", "syngenta"],
    "Ministerio de Produccion Comercio Exterior": ["bayer", "syngenta"],
    "Ministerio del Ambiente": ["bayer", "syngenta"],
    "Ministerio del Ambiente - Normativa": ["bayer", "syngenta"],
    "Agencia de Regulacion y Control Fito y Zoosanitario": ["bayer", "syngenta"],
    "Agrocalidad - Normativa": ["bayer", "syngenta"],
    "ARCSA (Regulacion Sanitaria)": ["bayer"],
    "ARCSA - Normativa": ["bayer"],
    "Proyectos normativos ARCSA": ["bayer"],
    "Ministerio de Salud Publica": ["bayer"],
    "Ministerio de Salud Publica - Normativa": ["bayer"],
    "IESS (Seg. Social)": ["bayer"],
    # Auditoria 2026-09-13: sacado "google" de estas 3 - el notas.md de
    # Google no tiene ninguna seccion de Ecuador (a diferencia de Incode,
    # que si distingue foco PE/EC explicitamente), asi que no hay base real
    # para asumir que la cuenta de Google cubre EC. Quedan sin cliente
    # hasta que Nicolas confirme si Google si tiene alcance EC.
    "Ministerio de Telecomunicaciones": [],
    "Ministerio de Telecomunicaciones - Normativa": [],
    "Superintendencia de Proteccion de Datos Personales": [],
    # Incode sigue el eje "relacion EEUU" en PE Y Ecuador (notas.md: "le
    # interesa el eje de relacion Peru/Ecuador-EEUU en general").
    "Ministerio de Relaciones Exteriores y Movilidad Humana": ["incode"],
    "Registro Civil (DIGERCIC)": ["incode"],
    "Google News EC — Cédula digital": ["incode"],

    # --- PE: cuentas X/Twitter institucionales (mismo tag que su fuente
    # gob.pe hermana cuando existe, en vez de caer al default generico
    # Institucion->todos que era impreciso para varias de estas) ---
    "X - PCM Peru (X)": ["todos"],
    "X - JNE Peru": [],
    "X - RENIEC Peru": ["incode"],  # foco explicito #1 de Incode (DNI digital/Confronte)
    "X - MIDAGRI Peru (X)": ["bayer", "syngenta"],
    "X - MINCETUR (X)": ["google", "bayer", "syngenta"],
    "X - Ositran": [],
    "X - Presidencia Peru (X)": ["todos"],
    "X - Defensoria del Pueblo": [],
    "X - MININTER Peru": [],
    "X - Cancilleria Peru": ["google"],
    "X - Congreso Peru (X)": ["todos"],
    "X - MINJUSDH Peru (X)": [],
    "X - PRODUCE Peru (X)": [],
    "X - MINEM Peru": [],
    "X - SGTD Peru Digital": ["google", "incode"],  # SGTD/PCM: gobierno digital, en ambos notas.md
}

CATEGORIA_CLIENTES: dict[str, list[str]] = {
    "Coyuntura Politica": ["todos"],
    "Institucion": ["todos"],
    "Temas Salud": ["bayer"],
    "Salud": ["bayer"],
    "Temas Agrarios": ["bayer", "syngenta"],
    "Agro": ["bayer", "syngenta"],
    "Temas Tech": ["google", "incode"],
    "Digital": ["google", "incode"],
    # Auditoria 2026-09-13: sacado "google" - su notas.md no menciona KYC/AML,
    # lavado de activos ni fintech en ningun lado (eso es foco explicito de
    # Incode, no de Google). Antes ambos entraban por error.
    "Temas KYC/AML": ["incode"],
    "Financiero": ["incode"],
}


# Instituciones que publican de TODO (presupuesto, RRHH, transferencias,
# macro...) y solo tienen UN angulo real relevante para el cliente con el
# que estan tageadas en INSTITUCION_CLIENTES (ej. MEF <-> Google es solo su
# decreto de IVA a plataformas digitales, no el resto de lo que emite MEF).
# Tagear la institucion entera trae ruido real (auditoria 2026-09-13). Para
# estas, ademas de aparecer en INSTITUCION_CLIENTES, el filtro Cliente exige
# que el TITULO+RESUMEN de la noticia matchee el tema real del cliente
# (noticias/temas.py::clasificar) - no es un ranking difuso tipo TF-IDF, es
# un mismo chequeo de keywords determinista/auditable que ya se usa para los
# badges "Temas" de la UI, aplicado tambien al filtro. Ver TEMAS_CLIENTE.
INSTITUCIONES_AMPLIAS: set[str] = {"MEF", "Salud con Lupa"}

# Fuentes "Coyuntura Politica" que en realidad traen el feed COMPLETO del
# sitio (deportes, espectaculos, policiales) por un feed especifico roto que
# cae a uno generico - ver noticias/scraper.py::_discover_rss ("auto-sana
# feeds rotos"). Auditoria 2026-09-13 (Nicolas: "siguen habiendo noticias que
# no tienen nada que ver"): verificado en vivo -
#   - El Universo EC: su rss_url declarado (.../rss/politica/) devuelve 404
#     ("Pagina no encontrada"), asi que cae al autodiscovery, que encuentra
#     el feed general del sitio (arc/outboundfeeds/rss, sin filtro de
#     seccion) - trae partidos de futbol, estrenos musicales, sucesos.
#   - El Comercio EC: su feed declarado (elcomercio.com/feed/) SI funciona,
#     pero es "Noticias del Ecuador y del mundo" (sitewide real, nunca fue
#     solo politica) - mismo problema, no un feed roto sino mal etiquetado.
# No hay un feed de solo-politica que funcione para ninguno de los dos (se
# probaron varias URLs candidatas). Filtro: exigir que el contenido matchee
# algun tema real (noticias/temas.py::clasificar) - independiente del
# cliente seleccionado, aplica incluso viendo "Todos", porque un partido de
# futbol no es "Coyuntura Politica" para nadie.
#
# 2026-09-14 (Nicolas: "chequea si sigue apareciendo ruido"): se encontro un
# 3er caso - "Bloomberg Linea Ecuador" (ya desactivada arriba, ver notas) -
# igual se agrega aca para limpiar las filas viejas ya scrapeadas (mercados
# LATAM/Fed/Argentina/Mexico, nada de Ecuador).
FUENTES_GENERALISTAS_FILTRAR_RUIDO: set[str] = {
    "El Universo", "El Comercio", "Bloomberg Linea Ecuador",
}

# Que tema(s) de noticias/temas.py::TEMAS le importan de verdad a cada
# cliente (de sus notas.md) - usado solo para las INSTITUCIONES_AMPLIAS de
# arriba, no reemplaza el tag por institucion/categoria de todos los demas.
TEMAS_CLIENTE: dict[str, list[str]] = {
    "google": ["Tech / Digital", "KYC / AML / Financiero"],
    "incode": ["Tech / Digital", "KYC / AML / Financiero"],
    "bayer": ["Salud", "Crop"],
    "syngenta": ["Crop"],
}

# Instituciones/categorias donde ni siquiera el tema generico de arriba
# alcanza - MINSA publica de todo (vacunacion infantil, campanas de anemia,
# traslados aeromedicos...) y esas notas SI matchean el tema "Salud" de
# temas.py porque "MINSA" es una de sus propias keywords (cualquier nota de
# MINSA "es sobre Salud" por definicion). Bayer se quejo (2026-09-13) de
# recibir justo ese tipo de salud publica general, que no tiene nada que ver
# con su bluebook real (registro sanitario/DIGEMID, abastecimiento,
# genericos, oncologia, hemofilia). Para estas, se exige ademas un match
# contra PERFIL_KEYWORDS (mas angosto y especifico que TEMAS_CLIENTE, sacado
# palabra por palabra del notas.md real del cliente) - DIGEMID NO esta acá:
# todo lo que publica DIGEMID ya es on-topic para Bayer (registro sanitario
# es su funcion misma), no necesita este filtro extra.
PERFIL_ESTRICTO: dict[str, set[str]] = {
    "bayer": {"MINSA", "Ministerio de Salud (estadisticas)",
              "Ministerio de Salud Publica", "Temas Salud", "Salud",
              "AgroPeru",
              # Auditoria 2026-09-13 (Nicolas: "siguen habiendo noticias que
              # no tienen nada que ver"): Andina agro/salud quedaron
              # desactivadas (codseccion roto, ver mas abajo) pero sus filas
              # viejas siguen en la DB y no tenian este filtro - traian
              # coyuntura politica generica ("Presidenta: este gobierno...")
              # tageada como salud/agro por error de clasificacion.
              "Andina (agencia oficial - agro)",
              "Andina (agencia oficial - salud)",
              # Mismo problema: Mundo Agropecuario (EC) es periodismo agrario
              # global generico (jardineria, clima, mercados de otros paises)
              # - las keywords Crop compartidas con syngenta ya filtran bien.
              "Mundo Agropecuario"},
    "syngenta": {"AgroPeru", "Andina (agencia oficial - agro)",
                 "Mundo Agropecuario"},
    # Auditoria 2026-09-13: 2 fuentes de Google News PE traen ruido real -
    # "Menores digitales" (verificacion de edad) matchea leyes de CUALQUIER
    # pais (Australia, Francia, Reino Unido) sin relacion con Peru/la region;
    # "KYC LAFT" trae guias de "como comprar cripto"/apuestas deportivas, no
    # regulacion. Mismo problema en EC: "DPL News Ecuador" (tageada KYC/AML)
    # es noticias de negocio tech/telecom generico, no identidad/AML; y
    # "Criptonoticias" (tageada Tech) es trading/mercado de cripto, no
    # regulacion. Exigir alguna senal regulatoria/institucional real.
    "google": {"Google News PE — Menores digitales", "Google News PE — KYC LAFT",
               "Criptonoticias"},
    "incode": {"Google News PE — Menores digitales", "Google News PE — KYC LAFT",
               "DPL News Ecuador", "Criptonoticias"},
}

PERFIL_KEYWORDS: dict[str, list[str]] = {
    "bayer": [
        "digemid", "registro sanitario", "farmacovigilancia", "venta libre",
        "generico", "oncolog", "cancer", "petitorio nacional", "pnume",
        "abastecimiento", "desabastecimiento", "essalud",
        "colegio de quimicos farmaceuticos", "hemofilia", "medicamento",
        "autoridad reguladora", "arcsa",
        # Crop (compartido con syngenta, ver abajo)
        "senasa", "plaguicida", "fitosanit", "semilla", "transgenic",
        "organismo vivo modificado", "agroecolog", "agricultura regenerativa",
        "agroexportacion", "autoridad nacional del agua", "biotecnolog",
    ],
    "syngenta": [
        # AgroPeru trae desarrollo rural general (riego, alpacas, cafe de
        # pequenos productores) - nada que ver con el interes real de
        # Syngenta (agroquimicos/semillas a escala comercial, no fomento
        # rural). Mismas keywords Crop que Bayer.
        "senasa", "plaguicida", "fitosanit", "semilla", "transgenic",
        "organismo vivo modificado", "agroecolog", "agricultura regenerativa",
        "agroexportacion", "autoridad nacional del agua", "biotecnolog",
    ],
    # Google/Incode: exige alguna senal regulatoria/institucional real (no
    # cualquier nota de "menores + redes sociales" o "cripto" de cualquier
    # pais - ver comentario en PERFIL_ESTRICTO arriba).
    #
    # ponytail (2026-09-14, Nicolas: "chequea si sigue apareciendo ruido"):
    # "peru"/"ecuador" sueltos se sacaron - dejaban pasar guias de apuestas
    # ("Betano verificar cuenta Peru: guia paso a paso") solo por mencionar
    # el pais, sin ninguna senal regulatoria real. Exigir un termino
    # institucional/legal es mas angosto pero evita ese falso positivo.
    "google": [
        "congreso", "asamblea nacional",
        "ley ", "proyecto de ley", "reglamento", "decreto", "regulacion",
        "sbs", "indecopi", "anpd", "mtc", "osiptel", "reniec",
        "clave unica", "ciberseguridad", "lavado de activos",
        "proteccion de datos", "banco central", "superintendencia",
    ],
    "incode": [
        "congreso", "asamblea nacional",
        "ley ", "proyecto de ley", "reglamento", "decreto", "regulacion",
        "sbs", "indecopi", "anpd", "mtc", "osiptel", "reniec",
        "clave unica", "ciberseguridad", "lavado de activos",
        "kyc", "identidad digital", "verificacion de identidad", "biometria",
        "proteccion de datos", "banco central", "superintendencia",
    ],
}


def _norm_kw(s: str | None) -> str:
    import unicodedata as _ud
    s = (s or "").lower()
    return "".join(c for c in _ud.normalize("NFD", s) if _ud.category(c) != "Mn")


def matchea_perfil(cliente: str, titulo: str | None, resumen: str | None) -> bool:
    """True si el texto matchea alguna keyword del bluebook real de `cliente`
    (PERFIL_KEYWORDS) - mas angosto que TEMAS_CLIENTE. Usado solo para
    instituciones/categorias en PERFIL_ESTRICTO; si el cliente no tiene
    perfil definido, no restringe (deja pasar, comportamiento previo)."""
    kws = PERFIL_KEYWORDS.get(cliente)
    if not kws:
        return True
    texto = _norm_kw(f"{titulo or ''} {resumen or ''}")
    return any(_norm_kw(kw) in texto for kw in kws)


def _clientes_de(fuente: dict) -> list[str]:
    """Resuelve la lista de clientes de una fuente: tag explicito del dict
    (si algun dia se agrega uno) > lookup por nombre > fallback por categoria."""
    if "clientes" in fuente:
        return fuente["clientes"]
    explicito = INSTITUCION_CLIENTES.get(fuente["nombre"])
    if explicito is not None:
        return explicito
    return CATEGORIA_CLIENTES.get(fuente["categoria"], [])


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
     "rss_url": "https://larepublica.pe/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: rss_url da 404, autodiscovery contra la "
              "home tampoco encontro un feed valido, verificado en vivo - "
              "cubierta igual por los periodistas de La Republica agregados via "
              "Google News (Martin Hidalgo, Adrian Sarria, etc.)."},
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
     "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: duplicada con el modulo scraper/ (API formal) que ya "
              "cubre esto - ademas el HTML de esta pagina (SPA) no trae items parseables por "
              "el scraper generico, 0 verificado en vivo."},
    {"categoria": "Institucion", "pais": "PE", "nombre": "El Peruano",
     "url": "https://elperuano.pe/", "tipo": "manual", "activa": 0,
     "notas": "Sin RSS ni HTML parseable; cubierto por Google News (queries de decretos abajo)"},
    # --- NORMATIVA PE (Google News: decretos, leyes, resoluciones) ---
    {"categoria": "Institucion", "pais": "PE",
     "nombre": "Google News PE — Decreto Supremo",
     "url": "https://news.google.com/rss/search?q=%22Decreto+Supremo%22+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "rss_url": "https://news.google.com/rss/search?q=%22Decreto+Supremo%22+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "tipo": "rss", "notas": "Query: 'Decreto Supremo' Peru"},
    {"categoria": "Institucion", "pais": "PE",
     "nombre": "Google News PE — Decreto de Urgencia",
     "url": "https://news.google.com/rss/search?q=%22Decreto+de+Urgencia%22+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "rss_url": "https://news.google.com/rss/search?q=%22Decreto+de+Urgencia%22+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "tipo": "rss", "notas": "Query: 'Decreto de Urgencia' Peru"},
    {"categoria": "Institucion", "pais": "PE",
     "nombre": "Google News PE — Ley promulgada",
     "url": "https://news.google.com/rss/search?q=Ley+promulgada+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "rss_url": "https://news.google.com/rss/search?q=Ley+promulgada+Peru&hl=es-419&gl=PE&ceid=PE:es",
     "tipo": "rss", "notas": "Query: Ley promulgada Peru"},
    {"categoria": "Institucion", "pais": "PE",
     "nombre": "Google News PE — El Peruano publica",
     "url": "https://news.google.com/rss/search?q=%22El+Peruano%22+publica+norma&hl=es-419&gl=PE&ceid=PE:es",
     "rss_url": "https://news.google.com/rss/search?q=%22El+Peruano%22+publica+norma&hl=es-419&gl=PE&ceid=PE:es",
     "tipo": "rss", "notas": "Query: 'El Peruano' publica norma - reemplaza feed de El Peruano"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Canal Congreso",
     "url": "https://canalncongreso.gob.pe/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
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

    # --- INSTITUCION PE: ministerios via gob.pe/busquedas.json ---
    # fetch_gobpe() (scraper.py) ya cubre noticias+normas de CUALQUIER
    # institucion gob.pe por slug - solo faltaba dar de alta cada ministerio
    # aca. categoria = vertical tematica (no "Institucion") cuando fetch_gobpe
    # debe traer tambien normas (ver regla en fetch_gobpe: activa normas si
    # la categoria contiene salud/agrari/kyc/aml), igual que ya hacia DIGEMID.
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "MINSA",
     "url": "https://www.gob.pe/institucion/minsa/noticias", "tipo": "gobpe"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "MIDAGRI",
     "url": "https://www.gob.pe/institucion/midagri/noticias", "tipo": "gobpe"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "SENASA",
     "url": "https://www.gob.pe/institucion/senasa/noticias", "tipo": "gobpe"},
    {"categoria": "Temas KYC/AML", "pais": "PE", "nombre": "MEF",
     "url": "https://www.gob.pe/institucion/mef/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "PCM",
     "url": "https://www.gob.pe/institucion/pcm/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "ANPD",
     "url": "https://www.gob.pe/institucion/anpd/noticias", "tipo": "gobpe",
     "notas": "Autoridad Nacional de Proteccion de Datos Personales - foco explicito "
              "de Google e Incode (privacidad/proteccion de datos)"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "RREE",
     "url": "https://www.gob.pe/institucion/rree/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MINEDU",
     "url": "https://www.gob.pe/institucion/minedu/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "PRODUCE",
     "url": "https://www.gob.pe/institucion/produce/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MINCETUR",
     "url": "https://www.gob.pe/institucion/mincetur/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MTC",
     "url": "https://www.gob.pe/institucion/mtc/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MINAM",
     "url": "https://www.gob.pe/institucion/minam/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Presidencia",
     "url": "https://www.gob.pe/institucion/presidencia/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "OSIPTEL",
     "url": "https://www.gob.pe/institucion/osiptel/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "INDECOPI",
     "url": "https://www.gob.pe/institucion/indecopi/noticias", "tipo": "gobpe"},

    # --- TEMAS AGRARIOS ---
                    {"categoria": "Temas Agrarios", "pais": "PE",
     "nombre": "CAP (Convencion Agropecuaria)",
     "url": "https://convencionagropecuaria.com.pe/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CONVEAGRO",
     "url": "https://www.conveagro.org.pe/",
     "rss_url": "https://www.conveagro.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Agraria.pe",
     "url": "https://agraria.pe/",
     "rss_url": "https://agraria.pe/rss", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: rss_url da 404, autodiscovery contra la home tampoco "
              "encontro un feed valido, verificado en vivo."},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "AGAP",
     "url": "https://agapperu.org/", "tipo": "html",
     "notas": "Asociacion de Gremios Productores Agrarios del Peru"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CEPES",
     "url": "https://www.cepes.org.pe/",
     "rss_url": "https://www.cepes.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Salud con Lupa",
     "url": "https://saludconlupa.com/noticias/", "tipo": "html",
     "notas": "Periodismo de investigacion (salud + regulacion agraria, ej. "
              "control de plaguicidas) - pedido explicito de Nicolas "
              "2026-09-16. En INSTITUCIONES_AMPLIAS: publican de todo "
              "(salud, social, etc.), el filtro de cliente exige que el "
              "titulo/resumen matcheen agro/salud de verdad, no toda la "
              "seccion 'noticias' del sitio."},
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
     "rss_url": "https://andina.pe/agencia/rss.aspx?codseccion=6", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-13: el parametro codseccion ya no filtra nada - probado en "
              "vivo del 1 al 10, TODOS devuelven el mismo feed generico (futbol, cine, policia,"
              " turismo). Estaba tageada bayer+syngenta y metia ruido real de todo tipo."},
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
     "rss_url": "https://fintechperu.com/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: HTTP 500 consistente en el feed, verificado en vivo "
              "(sitio con error, no problema de nuestro parser)."},
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
     "url": "https://www.digemid.minsa.gob.pe/webDigemid/publicaciones/normas-legales/",
     "tipo": "html",
     "notas": "Dominio propio (minsa.gob.pe/digemid), no esta en la plataforma gob.pe/"
              "institucion. Sin seccion 'noticias' separada - su contenido real son las "
              "resoluciones (normas-legales), verificado en vivo (17 items reales, 2026-09-12)"},
    {"categoria": "Temas Salud", "pais": "PE",
     "nombre": "Colegio de Quimicos Farmaceuticos del Peru",
     "url": "https://cqfp.pe/",
     "rss_url": "https://cqfp.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Voces Ciudadanas",
     "url": "https://vocesciudadanas.org.pe/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Esperantra",
     "url": "https://esperantra.org/",
     "rss_url": "https://esperantra.org/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: HTTP 503 consistente en el feed, verificado en vivo "
              "(sitio caido, no problema de nuestro parser)."},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Lazo Rosado",
     "url": "https://lazorosado.org/",
     "rss_url": "https://lazorosado.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE",
     "nombre": "Federacion Peruana de Enfermedades Raras",
     "url": "https://fepper.org.pe/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
    # --- Salud PE: portales nuevos ---
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Diario Medico Peru",
     "url": "https://diariomedico.pe/",
     "rss_url": "https://diariomedico.pe/feed/", "tipo": "rss",
     "notas": "Medio especializado salud/farma"},
    {"categoria": "Temas Salud", "pais": "PE",
     "nombre": "Andina (agencia oficial - salud)",
     "url": "https://andina.pe/agencia/seccion.aspx?codseccion=1",
     "rss_url": "https://andina.pe/agencia/rss.aspx?codseccion=1",
     "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-13: mismo bug que la fuente agro hermana - codseccion ya "
              "no filtra, devuelve el feed generico de Andina completo."},

    # --- TEMAS TECH ---
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Niubox Legal",
     "url": "https://niubox.legal/category/nius/",
     "rss_url": "https://niubox.legal/category/nius/feed/", "tipo": "rss",
     "notas": "Reactivada 2026-09-16: el feed viejo (niubox.legal/feed/) esta "
              "vacio, pero la matriz de monitoreo (investigado 2026-09-12) ya "
              "habia encontrado la URL real - es la categoria 'nius' "
              "(consultora legal, seccion de noticias/blog), no el home. RSS "
              "real verificado en vivo 2026-09-16 (10 items)."},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Comex Peru",
     "url": "https://www.comexperu.org.pe/",
     "rss_url": "https://www.comexperu.org.pe/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: rss_url da 404, autodiscovery contra la home "
              "tampoco encontro un feed valido, verificado en vivo. La home no tiene "
              "un listado de noticias parseable (solo paginas institucionales)."},
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
     "rss_url": "https://www.primicias.ec/rss/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: rss_url da 404 (PRIMICIAS descontinuo "
              "su RSS), y la pagina de politica es JS-rendered (los <h1-4> "
              "del HTML estatico son nombres de auspiciantes, no titulares "
              "reales - verificado en vivo) asi que tampoco sirve como html. "
              "Cubierto parcialmente por las queries de Google News EC."},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Gestion",
     "url": "https://www.revistagestion.ec/", "tipo": "html"},
    {"categoria": "Coyuntura Politica", "pais": "EC",
     "nombre": "Bloomberg Linea Ecuador",
     "url": "https://www.bloomberglinea.com/ecuador/",
     "rss_url": "https://www.bloomberglinea.com/arc/outboundfeeds/rss/?outputType=xml",
     "tipo": "rss", "activa": 0,
     "notas": "Auditoria 2026-09-14: el rss_url declarado NUNCA fue especifico "
              "de Ecuador - es el feed global del sitio (mercados LATAM, Fed, "
              "Argentina/Mexico/Colombia), verificado en vivo con 0 de 25 "
              "titulos recientes sobre Ecuador. No se encontro una URL de "
              "categoria Ecuador que funcione (probadas varias, todas 404). "
              "Se muestra a TODOS los clientes via categoria->todos, asi que "
              "traia ruido financiero global constante. Mismo patron que "
              "Andina codseccion (ver arriba)."},

    # --- INSTITUCION ---
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Asamblea Nacional - Proyectos de Ley",
     "url": "https://proyectosdeley.asambleanacional.gob.ec/",
     "tipo": "html",
     "notas": "Cubierto por modulo scraper_ec/"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Registro Oficial",
     "url": "https://www.registroficial.gob.ec/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: duplicada/redundante con "
              "'Registro Oficial EC (indice)' (ver noticias/registro_oficial_ec.py, "
              "que SI cubre ediciones principales y suplementos via PDF+OCR) - "
              "esta entrada usaba el scraper HTML generico contra una pagina "
              "de WordPress con indice-en-texto-plano que ese scraper no puede "
              "parsear, 0 noticias jamas (verificado contra la DB real)."},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Decretos Presidenciales",
     "url": "https://www.presidencia.gob.ec/decretos/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: pagina abandonada, un solo decreto listado "
              "(2021) - verificado en vivo. Los decretos reales se publican en el "
              "portal Minka (minka.presidencia.gob.ec), una app JSF sin listado "
              "HTML parseable."},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Registro Civil (DIGERCIC)",
     "url": "https://www.registrocivil.gob.ec/noticias/",
     "rss_url": "https://www.registrocivil.gob.ec/feed/", "tipo": "rss",
     "notas": "Cedula digital - foco explicito de Incode en Ecuador (verificado en vivo 2026-09-12)"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Google News EC — Cédula digital",
     "url": "https://news.google.com/rss/search?q=%22c%C3%A9dula+digital%22+Ecuador&hl=es-419&gl=EC&ceid=EC:es",
     "rss_url": "https://news.google.com/rss/search?q=%22c%C3%A9dula+digital%22+Ecuador&hl=es-419&gl=EC&ceid=EC:es",
     "tipo": "rss", "notas": "Query: 'cedula digital' Ecuador - complementa Registro Civil con cobertura de medios"},
    # Cobertura de normativa EC vía Google News
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Google News EC — Decreto Ejecutivo",
     "url": "https://news.google.com/rss/search?q=%22Decreto+Ejecutivo%22+Ecuador&hl=es-419&gl=EC&ceid=EC:es",
     "rss_url": "https://news.google.com/rss/search?q=%22Decreto+Ejecutivo%22+Ecuador&hl=es-419&gl=EC&ceid=EC:es",
     "tipo": "rss", "notas": "Query: 'Decreto Ejecutivo' Ecuador"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Google News EC — Registro Oficial",
     "url": "https://news.google.com/rss/search?q=%22Registro+Oficial%22+Ecuador&hl=es-419&gl=EC&ceid=EC:es",
     "rss_url": "https://news.google.com/rss/search?q=%22Registro+Oficial%22+Ecuador&hl=es-419&gl=EC&ceid=EC:es",
     "tipo": "rss", "notas": "Query: 'Registro Oficial' Ecuador"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Google News EC — Ley Orgánica",
     "url": "https://news.google.com/rss/search?q=%22Ley+Org%C3%A1nica%22+Ecuador+Asamblea&hl=es-419&gl=EC&ceid=EC:es",
     "rss_url": "https://news.google.com/rss/search?q=%22Ley+Org%C3%A1nica%22+Ecuador+Asamblea&hl=es-419&gl=EC&ceid=EC:es",
     "tipo": "rss", "notas": "Query: 'Ley Orgánica' Ecuador Asamblea"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Portal de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/",
     # Auditoria 2026-09-14 (Nicolas: "lo de noticias de la Asamblea no lo
     # has capturado, mi companera envio alertas de hoy que no sacaste"):
     # la URL vieja (.../es/noticias/feed) devuelve 404 en vivo - el sitio
     # se reestructuro. Verificado en vivo: la real es /es/rss.xml
     # (declarada como <link rel="alternate"> en la home del sitio).
     "rss_url": "https://www.asambleanacional.gob.ec/es/rss.xml",
     "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Agenda de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/es/agenda_de_comunicacion",
     "tipo": "html",
     "notas": "Cubierto por modulo agenda_ec/"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Ministerio de Economia y Finanzas",
     "url": "https://www.finanzas.gob.ec/category/comunicamos/noticias/",
     "rss_url": "https://www.finanzas.gob.ec/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: confirmado con la matriz de monitoreo "
              "(clientes/_plantillas/matriz_monitoreo/, investigado 2026-09-12) - "
              "Decreto Ejecutivo 425 (~19/06/2026) fusiono Agricultura+Finanzas+"
              "Produccion en el 'Ministerio de Desarrollo Economico y Productivo' "
              "(economicoproductivo.gob.ec). Reemplazada por esa fuente unica, "
              "ver mas abajo en Temas Agrarios."},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Ministerio de Relaciones Exteriores y Movilidad Humana",
     "url": "https://www.cancilleria.gob.ec/noticias-cancilleria/",
     "rss_url": "https://www.cancilleria.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "ARCSA (Regulacion Sanitaria)",
     "url": "https://www.controlsanitario.gob.ec/noticias/",
     "rss_url": "https://www.controlsanitario.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "ARCSA - Normativa",
     "url": "https://www.controlsanitario.gob.ec/documentos-vigentes/", "tipo": "html",
     "activa": 0,
     "notas": "Desactivada 2026-09-16: solo 4 PDFs listados en total, ninguno de "
              "los ultimos 3 anios - pagina practicamente abandonada, verificado "
              "en vivo."},

    # --- TEMAS AGRARIOS ---
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Resoluciones Ministerio de Agricultura",
     "url": "https://www.agricultura.gob.ec/normativa/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: la URL en realidad muestra 'Normativa "
              "Consejo Nacional de la Leche y sus Derivados' (nicho lacteo, no "
              "normativa agraria general), solo 2 PDFs - verificado en vivo. "
              "Ademas el dominio agricultura.gob.ec quedo obsoleto por la fusion "
              "ministerial (ver 'Ministerio de Desarrollo Economico y Productivo' "
              "mas abajo)."},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio de Agricultura y Ganaderia",
     "url": "https://www.agricultura.gob.ec/noticias/",
     "rss_url": "https://www.agricultura.gob.ec/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: confirmado con la matriz de monitoreo "
              "(investigado 2026-09-12) - Decreto Ejecutivo 425 (~19/06/2026) "
              "fusiono Agricultura+Finanzas+Produccion en el 'Ministerio de "
              "Desarrollo Economico y Productivo'. Reemplazada por esa fuente "
              "unica, ver mas abajo."},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio de Ambiente y Energia (MAE)",
     "url": "https://www.ambienteyenergia.gob.ec/noticias/",
     "rss_url": "https://www.ambienteyenergia.gob.ec/feed/", "tipo": "rss",
     "notas": "Fusion real 2025 (Decreto Ejecutivo 94, 14/08/2025): el viejo "
              "Ministerio del Ambiente, Agua y Transicion Ecologica fue absorbido "
              "por el de Energia y Minas - nuevo nombre y dominio "
              "ambienteyenergia.gob.ec (el viejo ambiente.gob.ec daba SSLError "
              "consistente). Confirmado con la matriz de monitoreo (investigado "
              "2026-09-12), RSS real verificado en vivo 2026-09-16 (10 items). "
              "Reemplaza 'Ministerio del Ambiente' y 'Ministerio del Ambiente - "
              "Normativa'."},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio de Desarrollo Economico y Productivo (MDEP)",
     "url": "https://www.economicoproductivo.gob.ec/noticias/",
     "rss_url": "https://www.economicoproductivo.gob.ec/feed/", "tipo": "rss",
     "notas": "Fusion real 2026 (Decreto Ejecutivo 425, oficializado "
              "~19/06/2026): unifica en una sola cartera lo que antes eran 3 "
              "ministerios separados (Agricultura y Ganaderia, Economia y "
              "Finanzas, Produccion/Comercio Exterior/Inversiones y Pesca) - los "
              "3 dominios viejos (agricultura.gob.ec, finanzas.gob.ec, "
              "produccion.gob.ec) quedan obsoletos. Confirmado con la matriz de "
              "monitoreo (investigado 2026-09-12), RSS real verificado en vivo "
              "2026-09-16 (10 items)."},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio del Ambiente",
     "url": "https://www.ambiente.gob.ec/noticias/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio viejo descontinuado, fusionado en "
              "'Ministerio de Ambiente y Energia (MAE)' - ver esa entrada, mismo "
              "dominio nuevo ambienteyenergia.gob.ec. SSLError consistente en "
              "pruebas en vivo (2026-09-12 y 2026-09-16)."},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio del Ambiente - Normativa",
     "url": "https://www.ambiente.gob.ec/normativa-1/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: mismo dominio viejo que 'Ministerio del "
              "Ambiente' - ver esa entrada y 'Ministerio de Ambiente y Energia "
              "(MAE)'."},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Ministerio de Produccion Comercio Exterior",
     "url": "https://www.produccion.gob.ec/noticias/",
     "rss_url": "https://www.produccion.gob.ec/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: confirmado con la matriz de monitoreo "
              "(investigado 2026-09-12) - Decreto Ejecutivo 425 (~19/06/2026) "
              "fusiono Agricultura+Finanzas+Produccion en el 'Ministerio de "
              "Desarrollo Economico y Productivo'. Reemplazada por esa fuente "
              "unica, ver mas arriba."},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Agencia de Regulacion y Control Fito y Zoosanitario",
     "url": "https://www.agrocalidad.gob.ec/category/noticias/",
     "rss_url": "https://www.agrocalidad.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "Agrocalidad - Normativa",
     "url": "https://www.agrocalidad.gob.ec/normativa-nacional-e-internacional/", "tipo": "html"},
    {"categoria": "Temas Agrarios", "pais": "EC",
     "nombre": "CONAIE (Confederacion Indigenas)",
     "url": "https://conaie.org/", "tipo": "html",
     "notas": "OJO (2026-09-16): HTTP 429 consistente contra IPs de datacenter "
              "(GH Actions Y probado en vivo aislado desde otra IP no residencial) "
              "- mismo patron que Ministerio del Ambiente EC. Se deja activa (no "
              "es un feed muerto, es un WAF agresivo) por si alguna corrida logra "
              "pasar; no se desactiva a mano."},
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
     "url": "https://www.telecomunicaciones.gob.ec/category/catactualidad/",
     "rss_url": "https://www.telecomunicaciones.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas KYC/AML", "pais": "EC",
     "nombre": "Ministerio de Telecomunicaciones - Normativa",
     "url": "https://www.telecomunicaciones.gob.ec/normativa/", "tipo": "html",
     "activa": 0,
     "notas": "Desactivada 2026-09-16: los PDFs listados son todos de 2017 - "
              "pagina abandonada, verificado en vivo."},
    {"categoria": "Temas KYC/AML", "pais": "EC",
     "nombre": "Superintendencia de Proteccion de Datos Personales",
     "url": "https://www.proteccionderechos.gob.ec/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
    {"categoria": "Temas KYC/AML", "pais": "EC", "nombre": "DPL News Ecuador",
     "url": "https://dplnews.com/",
     "rss_url": "https://dplnews.com/feed/", "tipo": "rss"},

    # --- TEMAS SALUD ---
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Proyectos normativos ARCSA",
     "url": "https://www.controlsanitario.gob.ec/proyectos-normativos/",
     "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: la pagina da HTTP 404, verificado en vivo (la URL real "
              "del sitio cambio o ya no existe esa seccion)."},
    {"categoria": "Temas Salud", "pais": "EC",
     "nombre": "Ministerio de Salud Publica",
     "url": "https://www.salud.gob.ec/noticias/",
     "rss_url": "https://www.salud.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "EC",
     "nombre": "Ministerio de Salud Publica - Normativa",
     "url": "https://www.salud.gob.ec/marco-normativo/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: la pagina no tiene ni un solo link a "
              "documento real (pdf/doc), verificado en vivo."},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "IESS (Seg. Social)",
     "url": "https://www.iess.gob.ec/es/web/guest/sala-de-prensa", "tipo": "html",
     "notas": "Timeout consistente en pruebas en vivo (2026-09-12), no se pudo confirmar RSS"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "ALAFAR Ecuador",
     "url": "https://www.alafar.org/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: alafar.org es la Asociacion Latinoamericana "
              "de Fabricantes de Refractarios (materiales industriales), NO la "
              "asociacion farmaceutica - colision de sigla, verificado en vivo "
              "(pagina real sobre refractarios, nada de salud/farma). Si existe "
              "una ALAFAR farmaceutica real, falta confirmar la URL correcta."},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "SOLCA Ecuador",
     "url": "https://www.solca.med.ec/", "tipo": "html",
     "notas": "OJO (2026-09-16): HTTP 403 consistente desde IPs de GH Actions "
              "(pero funciona bien, 17 items reales, probado desde otra IP) - "
              "mismo patron de bloqueo por IP de datacenter que CONAIE/Ambiente "
              "EC. Se deja activa por si alguna corrida logra pasar."},
    {"categoria": "Temas Salud", "pais": "EC",
     "nombre": "Jovenes Contra el Cancer Ecuador",
     "url": "https://jovenescontraelcancerec.org/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Pacientes Ecuador",
     "url": "https://pacientesecuador.org/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: HTTP 403 consistente incluso con el bypass "
              "de cloudscraper, verificado tanto desde GH Actions como desde otra "
              "IP - bot-block real del sitio, no problema de IP de datacenter "
              "como CONAIE/SOLCA."},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Edicion Medica",
     "url": "https://www.edicionmedica.ec/",
     "rss_url": "https://www.edicionmedica.ec/rss", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: rss_url da 404, autodiscovery contra la home tampoco "
              "encontro un feed valido, verificado en vivo."},

    # --- TEMAS TECH ---
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Criptonoticias",
     "url": "https://www.criptonoticias.com/",
     "rss_url": "https://www.criptonoticias.com/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "EC",
     "nombre": "Camara Ecuatoriana de Comercio Exterior",
     "url": "https://www.cce.org.ec/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Forbes Digital Ecuador",
     "url": "https://www.forbes.com.ec/",
     "rss_url": "https://www.forbes.com.ec/feed/", "tipo": "rss", "activa": 0,
     "notas": "Desactivada 2026-09-16: el feed responde HTTP 200 con XML valido "
              "pero <channel> sin ningun <item> adentro - feed vacio del lado del "
              "sitio, verificado en vivo (no es bug de nuestro parser)."},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "DPL Tech Ecuador",
     "url": "https://dplnews.com/", "tipo": "rss",
     "rss_url": "https://dplnews.com/feed/", "activa": 0,
     "notas": "Desactivada 2026-09-20: mismo feed EXACTO que 'DPL News Peru' "
              "(pais=PE) y 'DPL News Ecuador' (pais=EC, categoria KYC/AML) - "
              "3 filas de catalogo apuntando a dplnews.com/feed/. Como "
              "noticias.url es UNIQUE, cada articulo se lo queda la primera "
              "fila que sincroniza - esta siempre llega ultima (verificado en "
              "vivo: '[DPL Tech Ecuador] 10 items' cada corrida, 0 nuevas "
              "reales siempre). Fetch desperdiciado sin beneficio real -"
              " el pais real de cada articulo ya se corrige por contenido "
              "en noticias/temas.py:pais_por_contenido() via las otras 2."},
    {"categoria": "Temas Tech", "pais": "EC",
     "nombre": "Camara de Innovacion y Tecnologia Ecuatoriana",
     "url": "https://www.cite.org.ec/", "tipo": "html", "activa": 0,
     "notas": "Desactivada 2026-09-16: dominio no resuelve (DNS NXDOMAIN), verificado en vivo."},
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
    # Fase 3 (2026-09-13): Ecuador - las noticias se actualizan mas rapido
    # que el portal Ppless v2 (sync cada 4-6h via workflow, sin Playwright
    # en Streamlit Cloud). Estas queries cubren temas puntuales que las
    # matrices de Bayer Crop/Syngenta ya trackean a mano via comentarios de
    # actualizacion (confirmado: 0 de 2145 noticias EC citan el numero de
    # tramite exacto - no se puede cruzar por ID, solo por tema/keyword,
    # igual que ya hacia "Facultades legislativas" para PE). "clientes"
    # explicito (no categoria) para no depender del fallback "Agro".
    {**_gn("EC", "Agro", "Semillas transgenicos", "semillas+transgenicos+Ecuador+OVM"),
     "clientes": ["bayer", "syngenta"]},
    {**_gn("EC", "Agro", "Paramos OVM", "Ley+Paramos+Ecuador+organismos+geneticamente+modificados"),
     "clientes": ["bayer", "syngenta"]},
    {**_gn("EC", "Agro", "Drones agricolas", "aeronaves+no+tripuladas+Ecuador+ley"),
     "clientes": ["bayer", "syngenta"]},
    {**_gn("EC", "Agro", "INIAP biotecnologia", "INIAP+Ecuador+biotecnologia+ley"),
     "clientes": ["bayer", "syngenta"]},

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
    # Fase 3 (2026-09-13): igual que en Agro arriba, temas puntuales que la
    # matriz Incode EC ya trackea a mano. "clientes" explicito = ["incode"]
    # (NO uso la categoria "Digital", que via CATEGORIA_CLIENTES tambien
    # tagea a google - confirmado 2026-09-12 que Google no tiene alcance
    # EC en su notas.md, no hay base para asumirlo aca tampoco).
    {**_gn("EC", "Digital", "Ciberseguridad ley", "Ley+Organica+Ciberseguridad+Ecuador"),
     "clientes": ["incode"]},
    {**_gn("EC", "Digital", "Lavado activos COIP", "COIP+lavado+activos+Ecuador+personas+juridicas"),
     "clientes": ["incode"]},
    {**_gn("EC", "Digital", "Proteccion menores digital", "proteccion+menores+plataformas+digitales+Ecuador"),
     "clientes": ["incode"]},
    {**_gn("EC", "Digital", "Identidad digital IA", "clonacion+voz+identidad+digital+IA+Ecuador"),
     "clientes": ["incode"]},
    # INCODE regional (LATAM identity)
    _gn("PE", "Digital", "KYC LAFT", "KYC+lavado+activos+Peru"),
    _gn("PE", "Digital", "Registro SIM", "registro+chips+SIM+Peru"),

    # --- FINANCIERO / FINTECH ---
    _gn("PE", "Financiero", "SBS fintech", "SBS+fintech+Peru"),
    _gn("PE", "Financiero", "Finanzas abiertas", "finanzas+abiertas+Peru+open+finance"),

    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - Federacion Medica Peruana',
     "url": 'https://x.com/FMedicaPeruana',
     "rss_url": 'https://nitter.net/FMedicaPeruana/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - Colegio Medico Peru',
     "url": 'https://x.com/CMP_PERU',
     "rss_url": 'https://nitter.net/CMP_PERU/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - CMP Lima',
     "url": 'https://x.com/CMPLIMAIII',
     "rss_url": 'https://nitter.net/CMPLIMAIII/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - Edson Aguilar',
     "url": 'https://x.com/EdsonAguilar20',
     "rss_url": 'https://nitter.net/EdsonAguilar20/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - Instituto Nacional de Salud',
     "url": 'https://x.com/INS_Peru',
     "rss_url": 'https://nitter.net/INS_Peru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - Voces Ciudadanas',
     "url": 'https://x.com/VocesCiudadana2',
     "rss_url": 'https://nitter.net/VocesCiudadana2/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - SuSalud Peru',
     "url": 'https://x.com/SuSaludPeru',
     "rss_url": 'https://nitter.net/SuSaludPeru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - EsSalud Peru',
     "url": 'https://x.com/EsSaludPeru',
     "rss_url": 'https://nitter.net/EsSaludPeru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - SIS Peru',
     "url": 'https://x.com/SISPeruOficial',
     "rss_url": 'https://nitter.net/SISPeruOficial/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - ONG Esperantra',
     "url": 'https://x.com/OngEsperantra',
     "rss_url": 'https://nitter.net/OngEsperantra/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - Ernesto Bustamante',
     "url": 'https://x.com/ErnesBustamante',
     "rss_url": 'https://nitter.net/ErnesBustamante/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - CQFDL',
     "url": 'https://x.com/CQFDL',
     "rss_url": 'https://nitter.net/CQFDL/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - ESPERANTRA',
     "url": 'https://x.com/ESPERANTRA',
     "rss_url": 'https://nitter.net/ESPERANTRA/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - OPS/OMS Peru',
     "url": 'https://x.com/OPSOMSPeru',
     "rss_url": 'https://nitter.net/OPSOMSPeru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - MINSA Peru',
     "url": 'https://x.com/Minsa_Peru',
     "rss_url": 'https://nitter.net/Minsa_Peru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Salud', "pais": 'PE',
     "nombre": 'X - Cayetano Heredia',
     "url": 'https://x.com/CayetanoHeredia',
     "rss_url": 'https://nitter.net/CayetanoHeredia/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - FEDEXPOR',
     "url": 'https://x.com/Fedexpor',
     "rss_url": 'https://nitter.net/Fedexpor/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - AGROBAN',
     "url": 'https://x.com/AgrobanEC',
     "rss_url": 'https://nitter.net/AgrobanEC/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Agronegocios EC',
     "url": 'https://x.com/redagronegocios',
     "rss_url": 'https://nitter.net/redagronegocios/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - SENAE Aduana',
     "url": 'https://x.com/SENAE_Aduana',
     "rss_url": 'https://nitter.net/SENAE_Aduana/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - El Productor EC (X)',
     "url": 'https://x.com/ElproductorEC',
     "rss_url": 'https://nitter.net/ElproductorEC/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Ambiente y Energia EC',
     "url": 'https://x.com/EcuadorMAE',
     "rss_url": 'https://nitter.net/EcuadorMAE/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - CORPEI',
     "url": 'https://x.com/Corpei',
     "rss_url": 'https://nitter.net/Corpei/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Agrocalidad EC (X)',
     "url": 'https://x.com/AgrocalidadEC',
     "rss_url": 'https://nitter.net/AgrocalidadEC/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Finanzas EC / Desarrollo',
     "url": 'https://x.com/FinanzasEc',
     "rss_url": 'https://nitter.net/FinanzasEc/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - INIAP EC',
     "url": 'https://x.com/INIAPECUADOR',
     "rss_url": 'https://nitter.net/INIAPECUADOR/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - ANECACAO EC',
     "url": 'https://x.com/Anecacao_Ecu',
     "rss_url": 'https://nitter.net/Anecacao_Ecu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Tanlly Vera',
     "url": 'https://x.com/TanllyVera',
     "rss_url": 'https://nitter.net/TanllyVera/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Antonio Hidalgo',
     "url": 'https://x.com/antoniohidalgom',
     "rss_url": 'https://nitter.net/antoniohidalgom/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Agricultura EC (MAG)',
     "url": 'https://x.com/AgriculturaEc',
     "rss_url": 'https://nitter.net/AgriculturaEc/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Produccion EC',
     "url": 'https://x.com/Produccion_Ecu',
     "rss_url": 'https://nitter.net/Produccion_Ecu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Temas Agrarios', "pais": 'EC',
     "nombre": 'X - Ines Manzano',
     "url": 'https://x.com/inesmanzano',
     "rss_url": 'https://nitter.net/inesmanzano/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - ATV Noticias',
     "url": 'https://x.com/atv_noticias',
     "rss_url": 'https://nitter.net/atv_noticias/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Diario Trome',
     "url": 'https://x.com/tromepe',
     "rss_url": 'https://nitter.net/tromepe/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Hildebrandt en sus 13',
     "url": 'https://x.com/ensustrece',
     "rss_url": 'https://nitter.net/ensustrece/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Rosa Maria Palacios',
     "url": 'https://x.com/rmapalacios',
     "rss_url": 'https://nitter.net/rmapalacios/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - IDL Reporteros',
     "url": 'https://x.com/IDL_R',
     "rss_url": 'https://nitter.net/IDL_R/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Diario Gestion (X)',
     "url": 'https://x.com/Gestionpe',
     "rss_url": 'https://nitter.net/Gestionpe/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Diario Correo',
     "url": 'https://x.com/diariocorreo',
     "rss_url": 'https://nitter.net/diariocorreo/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Latina Noticias',
     "url": 'https://x.com/Latina_Noticias',
     "rss_url": 'https://nitter.net/Latina_Noticias/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - La Republica (X)',
     "url": 'https://x.com/larepublica_pe',
     "rss_url": 'https://nitter.net/larepublica_pe/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - America Noticias',
     "url": 'https://x.com/noticiAmerica',
     "rss_url": 'https://nitter.net/noticiAmerica/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - TV Peru Noticias',
     "url": 'https://x.com/noticias_tvperu',
     "rss_url": 'https://nitter.net/noticias_tvperu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Cuarto Poder',
     "url": 'https://x.com/Cuarto_Poder',
     "rss_url": 'https://nitter.net/Cuarto_Poder/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - Agencia Andina (X)',
     "url": 'https://x.com/Agencia_Andina',
     "rss_url": 'https://nitter.net/Agencia_Andina/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - CNN en Espanol',
     "url": 'https://x.com/CNNEE',
     "rss_url": 'https://nitter.net/CNNEE/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'Martin Hidalgo (periodista, via Google News)',
     "url": 'https://x.com/martinhidalgo',
     "rss_url": 'https://news.google.com/rss/search?q=%22Martin+Hidalgo%22+Congreso&hl=es-419&gl=PE&ceid=PE:es',
     "tipo": "rss",
     "notas": "nitter.net murio (X mando cese y desista a Nitter ago-2026); se sigue via Google "
              "News (cuando un medio retoma su primicia) en vez de leer el tuit directo, sin usar "
              "cuentas de X ni credenciales (decision de Nicolas 2026-09-12: no arriesgar su cuenta "
              "personal para scraping no oficial)"},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'Erik Rivera (periodista El Comercio, via Google News)',
     "url": 'https://x.com/ErikRivera__',
     "rss_url": 'https://news.google.com/rss/search?q=%22Erik+Rivera%22+Congreso&hl=es-419&gl=PE&ceid=PE:es',
     "tipo": "rss",
     "notas": "Periodista de politica/Congreso en El Comercio. Mismo approach via Google News que "
              "Martin Hidalgo - ver esa nota."},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'Adrian Sarria (periodista La Republica, via Google News)',
     "url": 'https://x.com/AdrianSarriaMu',
     "rss_url": 'https://news.google.com/rss/search?q=%22Adri%C3%A1n+Sarria%22&hl=es-419&gl=PE&ceid=PE:es',
     "tipo": "rss",
     "notas": "Periodista de la Unidad de Investigacion de La Republica (DDHH, corrupcion, gestion "
              "publica). Mismo approach via Google News - ver nota de Martin Hidalgo."},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'Erika Vasquez Salazar (periodista La Republica, via Google News)',
     "url": 'https://x.com/Ervasa2',
     "rss_url": 'https://news.google.com/rss/search?q=%22Erika+V%C3%A1squez+Salazar%22+Congreso&hl=es-419&gl=PE&ceid=PE:es',
     "tipo": "rss",
     "notas": "Periodista de La Republica, cubre Congreso/oposicion. Mencionada por Nicolas "
              "2026-09-12 (publico la carta de bancadas de oposicion pidiendo al oficialismo una "
              "nueva carta de facultades legislativas) pero quedo sin agregar en esa tanda - "
              "confirmado el nombre real por Nicolas 2026-09-13. Mismo approach via Google News - "
              "ver nota de Martin Hidalgo. OJO (2026-09-13): probado en vivo, esta query por su "
              "nombre no trae articulos reales todavia (a diferencia de Erik Rivera) - ver la "
              "fuente 'Facultades legislativas - oposicion' de abajo, que SI engancha esta misma "
              "cobertura por tema en vez de por firma."},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'Google News PE — Facultades legislativas (oposicion)',
     "url": 'https://news.google.com/rss/search?q=bancadas+oposicion+facultades+legislativas&hl=es-419&gl=PE&ceid=PE:es',
     "rss_url": 'https://news.google.com/rss/search?q=bancadas+oposicion+facultades+legislativas&hl=es-419&gl=PE&ceid=PE:es',
     "tipo": "rss",
     "notas": "Query por tema, no por periodista puntual - la busqueda por nombre de Erika Vasquez "
              "Salazar (arriba) no trae nada en vivo, pero esta si trae la cobertura real del angulo "
              "de la oposicion (ej. 'Oposicion pide al Gobierno presentar nuevo proyecto de "
              "facultades legislativas centrado en seguridad y El Nino' - Infobae, verificado en "
              "vivo 2026-09-13). Mas robusto que depender de que un medio cite a un periodista por "
              "nombre."},
    {"categoria": 'Coyuntura Politica', "pais": 'PE',
     "nombre": 'X - RPP Noticias (X)',
     "url": 'https://x.com/RPPNoticias',
     "rss_url": 'https://nitter.net/RPPNoticias/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - PCM Peru (X)',
     "url": 'https://x.com/pcmperu',
     "rss_url": 'https://nitter.net/pcmperu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - JNE Peru',
     "url": 'https://x.com/JNE_Peru',
     "rss_url": 'https://nitter.net/JNE_Peru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - RENIEC Peru',
     "url": 'https://x.com/ReniecPeru',
     "rss_url": 'https://nitter.net/ReniecPeru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - MIDAGRI Peru (X)',
     "url": 'https://x.com/midagriperu',
     "rss_url": 'https://nitter.net/midagriperu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - MINCETUR (X)',
     "url": 'https://x.com/MINCETUR',
     "rss_url": 'https://nitter.net/MINCETUR/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - Ositran',
     "url": 'https://x.com/ositranperu',
     "rss_url": 'https://nitter.net/ositranperu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - Presidencia Peru (X)',
     "url": 'https://x.com/presidenciaperu',
     "rss_url": 'https://nitter.net/presidenciaperu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - Defensoria del Pueblo',
     "url": 'https://x.com/Defensoria_Peru',
     "rss_url": 'https://nitter.net/Defensoria_Peru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - MININTER Peru',
     "url": 'https://x.com/MininterPeru',
     "rss_url": 'https://nitter.net/MininterPeru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - Cancilleria Peru',
     "url": 'https://x.com/CancilleriaPeru',
     "rss_url": 'https://nitter.net/CancilleriaPeru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - Congreso Peru (X)',
     "url": 'https://x.com/congresoperu',
     "rss_url": 'https://nitter.net/congresoperu/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - MINJUSDH Peru (X)',
     "url": 'https://x.com/MinjusDH_Peru',
     "rss_url": 'https://nitter.net/MinjusDH_Peru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - PRODUCE Peru (X)',
     "url": 'https://x.com/MINPRODUCCION',
     "rss_url": 'https://nitter.net/MINPRODUCCION/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - MINEM Peru',
     "url": 'https://x.com/MinemPeru',
     "rss_url": 'https://nitter.net/MinemPeru/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
    {"categoria": 'Institucion', "pais": 'PE',
     "nombre": 'X - SGTD Peru Digital',
     "url": 'https://x.com/PeruPaisDigital',
     "rss_url": 'https://nitter.net/PeruPaisDigital/rss', "tipo": "rss",
     "notas": "X/Twitter via nitter.net (rate-limited)"},
]


def all_fuentes() -> list[dict]:
    fuentes = FUENTES_PE + FUENTES_EC + FUENTES_GOOGLE_NEWS
    for f in fuentes:
        f.setdefault("clientes", _clientes_de(f))
        # Bug real 2026-09-16: las ~125 fuentes "X - ..." (cuentas de
        # X/Twitter) dependen todas de nitter.net (frontend publico de X sin
        # API oficial) para tener RSS - verificado en vivo que nitter.net ya
        # no responde (curl: connection failed, HTTP 000). Nunca trajeron
        # una sola noticia real (confirmado contra la DB de produccion: 63
        # fuentes activas, 0 noticias en cualquiera). Se desactivan aca, en
        # un solo lugar, en vez de tocar cada uno de los ~125 dict literals -
        # upsert_fuente() vuelve a escribir "activa" en cada corrida de
        # seed, asi que esto se aplica solo, sin tocar la DB a mano.
        if "nitter.net" in (f.get("rss_url") or ""):
            f["activa"] = 0
            f["notas"] = ((f.get("notas") or "") + " | DESACTIVADA 2026-09-16: "
                          "nitter.net no responde (HTTP 000), nunca trajo "
                          "nada real.").strip(" |")
    return fuentes
