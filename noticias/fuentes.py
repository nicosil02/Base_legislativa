"""Catalogo de fuentes de noticias (Peru + Ecuador).

Cada fuente es un dict: categoria, pais, nombre, url, rss_url, tipo, notas
(y opcionalmente activa, clientes). Tipos: rss, html, gobpe (API de gob.pe),
twitter y manual (estos dos no se scrapean). `cli seed` las copia a la DB;
las que se sacan de aca quedan desactivadas por deactivate_fuentes_huerfanas.

Cada fuente termina con una lista `clientes` (slugs de clientes/<slug>/, o
"todos") resuelta por `_clientes_de()`: tag explicito del dict, si no
INSTITUCION_CLIENTES por nombre, si no CATEGORIA_CLIENTES por categoria.
"""
from urllib.parse import quote_plus

from clientes import config
from core.text import sin_tildes

# Fuentes de todos los clientes (backbone legislativo/politico) o de ninguno.
# Las de cada cliente estan en clientes/<slug>/cliente.json ("instituciones").
INSTITUCION_CLIENTES: dict[str, list[str]] = {
    # --- PE: backbone legislativo/politico general ---
    "Google News PE — Decreto Supremo": ["todos"],
    "Google News PE — Decreto de Urgencia": ["todos"],
    "Google News PE — Ley promulgada": ["todos"],
    "Google News PE — El Peruano publica": ["todos"],
    "Agenda del Congreso": ["todos"],
    "PCM": ["todos"],
    "Presidencia": ["todos"],
    "MINEDU": [],
    "PRODUCE": [],
    "Direccion de Casinos (Apuestas Deportivas)": [],
    # --- EC: backbone legislativo/politico general ---
    "Asamblea Nacional - Proyectos de Ley": ["todos"],
    "Google News EC — Decreto Ejecutivo": ["todos"],
    "Google News EC — Registro Oficial": ["todos"],
    "Google News EC — Ley Orgánica": ["todos"],
    "Portal de la Asamblea Nacional": ["todos"],
    "Agenda de la Asamblea Nacional": ["todos"],
    # Google no cubre Ecuador (clientes/google/cliente.json): sin cliente.
    "Ministerio de Telecomunicaciones": [],
}
for _inst, _slugs in config.por_campo("instituciones").items():
    INSTITUCION_CLIENTES.setdefault(_inst, []).extend(_slugs)

CATEGORIA_CLIENTES: dict[str, list[str]] = {
    "Coyuntura Politica": ["todos"],
    "Institucion": ["todos"],
    **config.por_campo("categorias_fuente"),
}


# Instituciones que publican de todo y tienen un solo angulo real para su
# cliente (MEF <-> Google = IVA digital): el filtro Cliente exige ademas que
# el titulo+resumen matchee TEMAS_CLIENTE via temas.clasificar.
INSTITUCIONES_AMPLIAS: set[str] = {"MEF", "Salud con Lupa"}

# Medios cuyo feed trae el sitio completo (deportes, espectaculos,
# policiales), no solo politica: El Universo cae a su feed general porque el
# de politica da 404, El Comercio EC nunca tuvo uno solo de politica. Se
# exige que el contenido matchee algun tema. Incluye fuentes ya desactivadas
# para filtrar sus filas viejas en la DB.
FUENTES_GENERALISTAS_FILTRAR_RUIDO: set[str] = {
    "El Universo", "El Comercio", "Bloomberg Linea Ecuador",
    "Gestion", "La Republica", "RPP", "Infobae Peru", "Andina", "Expreso", "Canal N",
    "PRIMICIAS", "Expreso EC", "La Hora", "Vistazo", "Ecuavisa", "Teleamazonas", "El Telegrafo",
}

# Por cliente, de clientes/<slug>/cliente.json (ver clientes/config.py):
# TEMAS_CLIENTE solo se usa en INSTITUCIONES_AMPLIAS; PERFIL_ESTRICTO son las
# fuentes donde el tema generico no alcanza (todo MINSA es "Salud", pero a
# Bayer solo le sirve su bluebook) y se exige ademas una de PERFIL_KEYWORDS.
TEMAS_CLIENTE: dict[str, list[str]] = config.campo("temas_noticias")
PERFIL_ESTRICTO: dict[str, set[str]] = {k: set(v) for k, v in config.campo("fuentes_con_perfil_estricto").items()}
PERFIL_KEYWORDS: dict[str, list[str]] = config.campo("palabras_clave")


def _norm_kw(s: str | None) -> str:
    # Sin colapsar espacios: "ley " busca la palabra suelta.
    return sin_tildes((s or "").lower())


def matchea_perfil(cliente: str, titulo: str | None, resumen: str | None) -> bool:
    """True si el texto matchea alguna keyword de PERFIL_KEYWORDS[cliente].
    Cliente sin perfil: no restringe."""
    kws = PERFIL_KEYWORDS.get(cliente)
    if not kws:
        return True
    texto = _norm_kw(f"{titulo or ''} {resumen or ''}")
    return any(_norm_kw(kw) in texto for kw in kws)


def _clientes_de(fuente: dict) -> list[str]:
    """Tag explicito del dict > lookup por nombre > fallback por categoria."""
    if "clientes" in fuente:
        return fuente["clientes"]
    explicito = INSTITUCION_CLIENTES.get(fuente["nombre"])
    if explicito is not None:
        return explicito
    return CATEGORIA_CLIENTES.get(fuente["categoria"], [])


# Google News expone sus busquedas como RSS, sin API key.
def _gn(pais: str, categoria: str, nombre: str, query: str) -> dict:
    url = f"https://news.google.com/rss/search?q={query}&hl=es-419&gl={pais}&ceid={pais}:es"
    return {"categoria": categoria, "pais": pais, "nombre": f"Google News {pais} — {nombre}",
            "url": url, "rss_url": url, "tipo": "rss", "notas": f"Query: {query}"}


# ============================================================
# PERU
# ============================================================
FUENTES_PE: list[dict] = [
    # --- COYUNTURA POLITICA: medios principales ---
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "El Comercio",
     "url": "https://elcomercio.pe/politica/",
     "rss_url": "https://elcomercio.pe/arcio/rss/category/politica/", "tipo": "rss", "notas": "Reactivada 2026-09-27: el feed funciona (probado en vivo, notas del mismo dia). La nota vieja de feed roto estaba desactualizada."},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Gestion",
     "url": "https://gestion.pe/politica/",
     "rss_url": "https://gestion.pe/arcio/rss/category/peru/", "tipo": "rss", "notas": "Reactivada 2026-09-27: el feed funciona (probado en vivo, notas del mismo dia). La nota vieja de feed roto estaba desactualizada."},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "La Republica",
     "url": "https://larepublica.pe/politica",
     "rss_url": "https://larepublica.pe/rss/politica.xml", "tipo": "rss", "notas": "Reactivada 2026-09-27: el feed funciona (probado en vivo, notas del mismo dia). La nota vieja de feed roto estaba desactualizada."},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Peru 21",
     "url": "https://peru21.pe/politica/",
     "rss_url": "https://peru21.pe/arcio/rss/category/politica/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "RPP",
     "url": "https://rpp.pe/politica",
     "rss_url": "https://rpp.pe/feed/politica", "tipo": "rss", "notas": "Reactivada 2026-09-27: el feed funciona (probado en vivo, notas del mismo dia). La nota vieja de feed roto estaba desactualizada."},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Congrezoo",
     "url": "https://congrezoo.pe/",
     "rss_url": "https://congrezoo.pe/feed/", "tipo": "rss",
     "notas": "Alerta parlamentaria que sube los documentos oficiales en PDF (pedido de facultades, "
              "exposicion de motivos, dictamenes). Agregado por Nicolas 2026-09-29; feed probado en vivo."},
    # Los medios sin RSS propio entran por Google News filtrado al dominio.
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Infobae Peru",
     "url": "https://www.infobae.com/peru/",
     "rss_url": "https://www.infobae.com/arc/outboundfeeds/rss/category/peru/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Andina",
     "url": "https://andina.pe/",
     "rss_url": "https://andina.pe/agencia/rss.aspx", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "IDL-Reporteros",
     "url": "https://idl-reporteros.pe/",
     "rss_url": "https://idl-reporteros.pe/feed/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Expreso",
     "url": "https://www.expreso.com.pe/",
     "rss_url": "https://news.google.com/rss/search?q=site:expreso.com.pe+when:1d&hl=es-419&gl=PE&ceid=PE:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Canal N",
     "url": "https://canaln.pe/",
     "rss_url": "https://news.google.com/rss/search?q=site:canaln.pe+when:1d&hl=es-419&gl=PE&ceid=PE:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Ojo Publico",
     "url": "https://ojo-publico.com/",
     "rss_url": "https://news.google.com/rss/search?q=site:ojo-publico.com+when:3d&hl=es-419&gl=PE&ceid=PE:es", "tipo": "rss"},
    # epicentro.tv no tiene RSS (/feed da 404); Google News si lo indexa.
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Epicentro TV",
     "url": "https://epicentro.tv/",
     "rss_url": "https://news.google.com/rss/search?q=site:epicentro.tv+when:3d&hl=es-419&gl=PE&ceid=PE:es", "tipo": "rss"},

    # --- NORMATIVA PE (Google News: decretos, leyes, resoluciones) ---
    _gn("PE", "Institucion", "Decreto Supremo", "%22Decreto+Supremo%22+Peru"),
    _gn("PE", "Institucion", "Decreto de Urgencia", "%22Decreto+de+Urgencia%22+Peru"),
    _gn("PE", "Institucion", "Ley promulgada", "Ley+promulgada+Peru"),
    _gn("PE", "Institucion", "El Peruano publica", "%22El+Peruano%22+publica+norma"),
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
    # fetch_gobpe trae normas solo si la categoria contiene salud/agrari/
    # kyc/aml: por eso algunas van con categoria tematica y no "Institucion".
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
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CONVEAGRO",
     "url": "https://www.conveagro.org.pe/",
     "rss_url": "https://www.conveagro.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "AGAP",
     "url": "https://agapperu.org/", "tipo": "html",
     "notas": "Asociacion de Gremios Productores Agrarios del Peru"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CEPES",
     "url": "https://www.cepes.org.pe/",
     "rss_url": "https://www.cepes.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Salud con Lupa",
     "url": "https://saludconlupa.com/noticias/",
     # Categoria "Temas Agrarios" le ponia Crop a sus notas de salud y sociales.
     "rss_url": "https://saludconlupa.com/feed/", "tipo": "rss",
     "notas": "Periodismo de investigacion (salud + regulacion agraria, ej. "
              "control de plaguicidas) - pedido explicito de Nicolas "
              "2026-09-16. En INSTITUCIONES_AMPLIAS: publican de todo "
              "(salud, social, etc.), el filtro de cliente exige que el "
              "titulo/resumen matcheen agro/salud de verdad, no toda la "
              "seccion 'noticias' del sitio."},

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
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "AgroNoticias Peru",
     "url": "https://agronoticias.pe/",
     "rss_url": "https://agronoticias.pe/feed/", "tipo": "rss",
     "notas": "Portal noticias sector agrario peruano"},

    # --- KYC / AML / Financiero ---
    {"categoria": "Temas KYC/AML", "pais": "PE", "nombre": "SBS - Resoluciones",
     "url": "https://www.sbs.gob.pe/", "tipo": "html",
     "notas": "Superintendencia de Banca, Seguros y AFP - normativa"},
    _gn("PE", "Temas KYC/AML", "SUNAT", "SUNAT+Peru"),
    _gn("PE", "Temas KYC/AML", "BCRP", "BCRP+Peru"),
    _gn("PE", "Temas KYC/AML", "UIF lavado", "UIF+lavado+activos+Peru"),

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
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Lazo Rosado",
     "url": "https://lazorosado.org/",
     "rss_url": "https://lazorosado.org/feed/", "tipo": "rss"},
    # --- Normas antes de que salgan y compras publicas (investigado 2026-10-18) ---
    {"categoria": "Institucion", "pais": "PE", "nombre": "Prepublicaciones de normas (gob.pe)",
     "url": "https://www.gob.pe/busquedas?contenido[]=normas", "tipo": "gobpe",
     "busqueda": "disponen la publicacion del proyecto", "exige": r"publicaci[oó]n del proyecto",
     "notas": "Proyectos de norma de cualquier ministerio/regulador en consulta, antes de que "
              "salgan (ej. RM 00360-2026-PRODUCE, 17/10). Busqueda de texto completo de gob.pe."},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Prepublicaciones (fichas y reglamentos)",
     "url": "https://www.gob.pe/busquedas?contenido[]=normas", "tipo": "gobpe",
     "busqueda": "prepublicacion", "exige": r"pre-?publicaci[oó]n"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Compras publicas de medicamentos y salud (OECE)",
     "url": "https://contratacionesabiertas.oece.gob.pe/", "tipo": "oece",
     "terminos": ["medicamentos", "vacuna", "oncologico", "dispositivos medicos"],
     "notas": "API OCDS del SEACE, datos del mismo dia. Bayer farma."},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Compras publicas agro (OECE)",
     "url": "https://contratacionesabiertas.oece.gob.pe/", "tipo": "oece",
     "terminos": ["plaguicida", "fertilizante", "semillas certificadas"]},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Compras publicas identidad y tecnologia (OECE)",
     "url": "https://contratacionesabiertas.oece.gob.pe/", "tipo": "oece",
     "terminos": ["biometrico", "biometrica", "identidad digital", "inteligencia artificial"]},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "CENARES", "url": "https://www.gob.pe/cenares",
     "tipo": "gobpe", "notas": "Compras centralizadas de medicamentos del MINSA (sus normas)."},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "EsSalud", "url": "https://www.gob.pe/essalud",
     "tipo": "gobpe"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "DIGEMID - Alertas sanitarias",
     "url": "https://www.digemid.minsa.gob.pe/webDigemid/", "rss_url": "https://www.digemid.minsa.gob.pe/webDigemid/feed/",
     "tipo": "rss", "notas": "Alertas DIGEMID y acciones de seguridad en campo (Bayer farma)."},
    # --- Salud PE: portales nuevos ---
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Diario Medico Peru",
     "url": "https://diariomedico.pe/",
     "rss_url": "https://diariomedico.pe/feed/", "tipo": "rss",
     "notas": "Medio especializado salud/farma"},

    # --- TEMAS TECH ---
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Niubox Legal",
     "url": "https://niubox.legal/category/nius/",
     "rss_url": "https://niubox.legal/category/nius/feed/", "tipo": "rss",
     "notas": "Reactivada 2026-09-16: el feed viejo (niubox.legal/feed/) esta "
              "vacio, pero la matriz de monitoreo (investigado 2026-09-12) ya "
              "habia encontrado la URL real - es la categoria 'nius' "
              "(consultora legal, seccion de noticias/blog), no el home. RSS "
              "real verificado en vivo 2026-09-16 (10 items)."},
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
     "rss_url": "https://news.google.com/rss/search?q=site:primicias.ec+when:1d&hl=es-419&gl=EC&ceid=EC:es", "tipo": "rss",
     "notas": "2026-09-27: sin RSS propio (404 desde 2026-09-16) - entra por Google News filtrado al dominio, probado en vivo con notas del dia."},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Expreso EC",
     "url": "https://www.expreso.ec/",
     "rss_url": "https://news.google.com/rss/search?q=site:expreso.ec+when:1d&hl=es-419&gl=EC&ceid=EC:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "La Hora",
     "url": "https://www.lahora.com.ec/",
     "rss_url": "https://news.google.com/rss/search?q=site:lahora.com.ec+when:1d&hl=es-419&gl=EC&ceid=EC:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Vistazo",
     "url": "https://www.vistazo.com/",
     "rss_url": "https://news.google.com/rss/search?q=site:vistazo.com+when:1d&hl=es-419&gl=EC&ceid=EC:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Ecuavisa",
     "url": "https://www.ecuavisa.com/",
     "rss_url": "https://news.google.com/rss/search?q=site:ecuavisa.com+when:1d&hl=es-419&gl=EC&ceid=EC:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Teleamazonas",
     "url": "https://www.teleamazonas.com/",
     "rss_url": "https://news.google.com/rss/search?q=site:teleamazonas.com+when:1d&hl=es-419&gl=EC&ceid=EC:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "El Telegrafo",
     "url": "https://www.eltelegrafo.com.ec/",
     "rss_url": "https://news.google.com/rss/search?q=site:eltelegrafo.com.ec+when:1d&hl=es-419&gl=EC&ceid=EC:es", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Gestion",
     "url": "https://www.revistagestion.ec/", "tipo": "html"},

    # --- INSTITUCION ---
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Asamblea Nacional - Proyectos de Ley",
     "url": "https://proyectosdeley.asambleanacional.gob.ec/",
     "tipo": "html",
     "notas": "Cubierto por modulo scraper_ec/"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Registro Civil (DIGERCIC)",
     "url": "https://www.registrocivil.gob.ec/noticias/",
     "rss_url": "https://www.registrocivil.gob.ec/feed/", "tipo": "rss",
     "notas": "Cedula digital - foco explicito de Incode en Ecuador (verificado en vivo 2026-09-12)"},
    _gn("EC", "Institucion", "Cédula digital", "%22c%C3%A9dula+digital%22+Ecuador"),
    # Cobertura de normativa EC vía Google News
    _gn("EC", "Institucion", "Decreto Ejecutivo", "%22Decreto+Ejecutivo%22+Ecuador"),
    _gn("EC", "Institucion", "Registro Oficial", "%22Registro+Oficial%22+Ecuador"),
    _gn("EC", "Institucion", "Ley Orgánica", "%22Ley+Org%C3%A1nica%22+Ecuador+Asamblea"),
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Portal de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/",
     # El feed viejo (/es/noticias/feed) da 404; el real es /es/rss.xml.
     "rss_url": "https://www.asambleanacional.gob.ec/es/rss.xml",
     "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Agenda de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/es/agenda_de_comunicacion",
     "tipo": "html",
     "notas": "Cubierto por modulo agenda_ec/"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "Ministerio de Relaciones Exteriores y Movilidad Humana",
     "url": "https://www.cancilleria.gob.ec/noticias-cancilleria/",
     "rss_url": "https://www.cancilleria.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC",
     "nombre": "ARCSA (Regulacion Sanitaria)",
     "url": "https://www.controlsanitario.gob.ec/noticias/",
     "rss_url": "https://www.controlsanitario.gob.ec/feed/", "tipo": "rss"},

    # --- TEMAS AGRARIOS ---
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

    # --- PDFs que suben las instituciones (wp-json): resoluciones y borradores en
    # consulta antes del Registro Oficial (investigado 2026-10-18) ---
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "AIL EP - Noticias",
     "url": "https://ail.msp.gob.ec/noticias/", "rss_url": "https://ail.msp.gob.ec/feed/", "tipo": "rss",
     "notas": "Empresa publica de compra de medicinas (Decreto 393). De aca salio el listado de la "
              "ronda de compras 1 (oct 2026). msp.gob.ec no responde desde Peru (18/10): si GitHub "
              "tampoco llega, es geo-bloqueo y queda Google News."},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "AIL EP - Documentos publicados",
     "url": "https://ail.msp.gob.ec", "tipo": "wpmedia",
     "notas": "Listados de compras (ej. LISTADO-RONDA-COMPRAS-1.pdf). Ver nota de AIL EP - Noticias."},
    {"categoria": "Temas KYC/AML", "pais": "EC", "nombre": "SPDP - Documentos publicados",
     "url": "https://spdp.gob.ec", "tipo": "wpmedia",
     "notas": "Borradores de normas de datos personales en consulta (Incode). 15/10: datos de salud, "
              "portabilidad, datos crediticios."},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "Agrocalidad - Documentos publicados",
     "url": "https://www.agrocalidad.gob.ec", "tipo": "wpmedia",
     "notas": "Resoluciones y propuestas en consulta (RFI semillas, granos), Bayer/Syngenta crop."},
    {"categoria": "Institucion", "pais": "EC", "nombre": "SERCOP - Documentos publicados",
     "url": "https://portal.compraspublicas.gob.ec/sercop", "tipo": "wpmedia",
     "notas": "Resoluciones SERCOP sobre compras publicas."},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "MPCEIP - Documentos publicados",
     "url": "https://www.produccion.gob.ec", "tipo": "wpmedia"},
    # --- KYC / AML ---
    {"categoria": "Temas KYC/AML", "pais": "EC",
     "nombre": "Ministerio de Telecomunicaciones",
     "url": "https://www.telecomunicaciones.gob.ec/category/catactualidad/",
     "rss_url": "https://www.telecomunicaciones.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas KYC/AML", "pais": "EC", "nombre": "DPL News Ecuador",
     "url": "https://dplnews.com/",
     "rss_url": "https://dplnews.com/feed/", "tipo": "rss"},

    # --- TEMAS SALUD ---
    {"categoria": "Temas Salud", "pais": "EC",
     "nombre": "Ministerio de Salud Publica",
     "url": "https://www.salud.gob.ec/noticias/",
     "rss_url": "https://www.salud.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "IESS (Seg. Social)",
     "url": "https://www.iess.gob.ec/es/web/guest/sala-de-prensa", "tipo": "html",
     "notas": "Timeout consistente en pruebas en vivo (2026-09-12), no se pudo confirmar RSS"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "SOLCA Ecuador",
     "url": "https://www.solca.med.ec/", "tipo": "html",
     "notas": "OJO (2026-09-16): HTTP 403 consistente desde IPs de GH Actions "
              "(pero funciona bien, 17 items reales, probado desde otra IP) - "
              "mismo patron de bloqueo por IP de datacenter que CONAIE/Ambiente "
              "EC. Se deja activa por si alguna corrida logra pasar."},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Edicion Medica",
     "url": "https://www.edicionmedica.ec/",
     "tipo": "html",
     "notas": "Reactivada 2026-09-27 (pedido de Nicolas) leyendo la portada en html: el RSS "
              "da 404 desde 2026-09-16 pero la portada trae ~27 notas, probado en vivo. "
              "No existe edicion Peru (edicionmedica.com.pe no resuelve)."},

    # --- TEMAS TECH ---
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Criptonoticias",
     "url": "https://www.criptonoticias.com/",
     "rss_url": "https://www.criptonoticias.com/feed/", "tipo": "rss"},
]


# ============================================================
# GOOGLE NEWS (busquedas por tema)
# ============================================================
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
    # Respaldo del portal de la Asamblea: desde el 24/09/2026 no publica los
    # proyectos nuevos (el ultimo presentado sigue siendo el 486423), y los
    # que salen en prensa no aparecen ahi (ej. ADN, licencias de migrantes, 09/10).
    _gn("EC", "Institucion", "Proyectos de ley presentados",
        "%22proyecto+de+ley%22+Ecuador+asamble%C3%ADsta+when:7d"),

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
    # PL de Ecuador que siguen las matrices de Bayer/Syngenta: la prensa los
    # cuenta antes que el portal de la Asamblea, y solo se cruzan por tema.
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
    # Igual, matriz Incode EC. Solo incode: la categoria "Digital" sumaria a
    # Google, que no cubre Ecuador.
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
    _gn("PE", "Coyuntura Politica", "Facultades legislativas (oposicion)", "bancadas+oposicion+facultades+legislativas"),
]


# ============================================================
# CUENTAS X
# ============================================================
# Cuentas de X. No hay lector de X (nitter murio, twscrape pide una cuenta
# aparte): las que tienen query se siguen por Google News (lo que la prensa
# publica sobre la persona o institucion); el resto queda activa=0, tipo
# "twitter". Prioridad A/B/C va en notas.
# Medios y agregadores no se buscan por nombre (trae ruido); nombres comunes
# llevan contexto en _GN_QUERY ("Fabiola Torres" sola traia Chile/Grecia).
_GN_QUERY = {
    "Fabiola Torres": '"Fabiola Torres" "Salud con Lupa"',
    "Camila Leon (Comision Biodiversidad)": '"Camila León" asambleísta',
    "Sara Ortiz": '"Sara Ortiz" Expreso',
    "Arturo Torres": '"Arturo Torres" "Código Vidrio"',
    "Carlos Vera": '"Carlos Vera" periodista Ecuador',
    "Monica Velasquez": '"Mónica Velásquez" periodista Ecuador',
    "Carlos Rojas Araujo": '"Carlos Rojas" "Políticamente Correcto"',
    "Alvaro Espinosa": '"Álvaro Espinosa" "El Balance"',
    "Cesar Romero": '"César Romero" "La República"',
    "Alfredo Torres (Ipsos)": '"Alfredo Torres" Ipsos',
    "Lima Gris": '"Lima Gris" revista',
    "Andrea Orbe": '"Andrea Orbe" periodista',
    "Fabricio Vela": '"Fabricio Vela" Ecuador',
    "Janet Hinostroza": '"Janet Hinostroza"',
    "MEF": '"MEF" Perú',
    "MTC (incluye DGAC, drones)": '"MTC" Perú drones OR aeronáutica OR telecomunicaciones',
    "DGAC Ecuador": '"Aviación Civil" Ecuador',
    "Tribunal Constitucional": '"Tribunal Constitucional" Perú',
    "Corte Constitucional": '"Corte Constitucional" Ecuador',
    "Contraloria": '"Contraloría" Perú',
    "Asamblea Nacional": '"Asamblea Nacional" Ecuador',
    "Ministerio de Salud Publica": '"Ministerio de Salud Pública" Ecuador',
    "IPE": '"Instituto Peruano de Economía"',
    "IEP": '"IEP" encuesta',
    "Transparencia": '"Asociación Civil Transparencia"',
    "Participacion Ciudadana": '"Participación Ciudadana" Ecuador',
    "Consorcio Agroecologico Peruano": '"Consorcio Agroecológico Peruano"',
    "Keiko Fujimori (Presidenta)": '"Keiko Fujimori"',
    "Luis Galarreta (PCM)": '"Luis Galarreta"',
    "Juan Sheput (Trabajo)": '"Juan Sheput"',
    "Vladimiro Huaroc (MINAM)": '"Vladimiro Huaroc" OR "ministro Huaroc"',
    "Susana Matute (Comision Salud Senado)": '"Susana Matute"',
    "Oscar Reto (Pdte. Diputados)": '"Óscar Reto" OR "Oscar Reto"',
    "Daniel Noboa (Presidente)": '"Daniel Noboa"',
    "Mishel Mancheno (Pdta. Asamblea)": '"Mishel Mancheno"',
    "Valentina Centeno (Comision Desarrollo Economico)": '"Valentina Centeno"',
    "Diego Macera (IPE)": '"Diego Macera"',
    "Milagros Leiva (programa)": '"Milagros Leiva"',
    "Erick Iriarte (IALaw)": '"Erick Iriarte"',
    "Agraria.pe": "site:agraria.pe",
    "Convoca": "site:convoca.pe",
    "GK": "site:gk.city",
}
_SIN_GN = {  # medios/agregadores ya cubiertos por su web, o sin query util
    "DiarioElPeruano", "saludconlupa", "Ojo_Publico", "Politica_LR", "canalN_",
    "infobaeperu", "exitosape", "peru21noticias", "willaxtv", "N60Noticias",
    "SudacaPeru", "MLEntrevista", "ipsosperu", "Presidencia_Ec", "ComunicacionEc",
    "TvlEcuador", "RegistrOficial", "Munagropecuario", "edicionmedEC", "primicias",
    "expresoec", "eluniversocom", "elcomerciocom", "revistavistazo", "ecuavisa",
    "EcuavisaInforma", "teleamazonasec", "ElBalance_EC", "politikcorrecta",
    "revistaPlanV", "RtpEcuador", "ecuainm_oficial", "lahoraecuador", "ElDatoEcua",
    "ladataec", "TiempoRealEC", "WRadioEc", "elmercuriomanta", "kchradio",
    "LaRadioAsamblea", "analisissemanal", "LupaMediaEC", "CodigoVidrioEc",
    "ECUADORCHEQUEA",
}


def _x(pais, categoria, nombre, handle, prio, clientes, nota):
    f = {"categoria": categoria, "pais": pais, "nombre": f"X - {nombre}",
         "url": f"https://x.com/{handle}", "tipo": "twitter", "activa": 0,
         "clientes": clientes, "notas": f"Prioridad {prio}. {nota}"}
    if handle not in _SIN_GN:
        q = quote_plus(_GN_QUERY.get(nombre) or f'"{nombre.split(" (")[0]}"')
        f.update(tipo="rss", activa=1,
                 rss_url=f"https://news.google.com/rss/search?q={q}&hl=es-419&gl={pais}&ceid={pais}:es",
                 notas=f["notas"] + " | Seguido via Google News (lo que la prensa publica sobre la cuenta, no el tuit).")
    return f


_T, _B, _S, _G, _I = ["todos"], ["bayer"], ["syngenta"], ["google"], ["incode"]
_CROP = _B + _S
_TECH = _G + _I

FUENTES_X_2026: list[dict] = [
    # --- PE: instituciones ---
    _x("PE", "Temas Agrarios", "SENASA", "Senasa_Peru", "A", _CROP, "gob.pe/senasa"),
    _x("PE", "Temas Agrarios", "MINAM", "MinamPeru", "A", _CROP, "gob.pe/minam"),
    _x("PE", "Institucion", "MEF", "MEF_Peru", "B", _T, "gob.pe/mef"),
    _x("PE", "Temas Tech", "INDECOPI", "IndecopiOficial", "B", _TECH, "gob.pe/indecopi"),
    _x("PE", "Institucion", "Tribunal Constitucional", "tc_peru", "B", _T, "tc.gob.pe"),
    _x("PE", "Institucion", "Contraloria", "ContraloriaPeru", "C", _T, "gob.pe/contraloria"),
    _x("PE", "Institucion", "SUNAT", "SUNATOficial", "B", _G, "sunat.gob.pe"),
    _x("PE", "Institucion", "El Peruano (diario oficial)", "DiarioElPeruano", "A", _T, "elperuano.pe"),
    _x("PE", "Institucion", "MTC (incluye DGAC, drones)", "MTC_GobPeru", "B", _CROP + _G, "gob.pe/mtc"),
    # --- PE: gremios, ONG y medios sectoriales ---
    _x("PE", "Temas Agrarios", "SPDA", "spdaorg", "B", _CROP, "spda.org.pe"),
    _x("PE", "Temas Agrarios", "CONVEAGRO", "CONVEAGROPERU", "A", _CROP, "conveagro.org.pe"),
    _x("PE", "Temas Agrarios", "AGAP", "AGAP_PERU", "A", _CROP, "x.com/agap_peru"),
    _x("PE", "Temas Agrarios", "Consorcio Agroecologico Peruano", "CAP_Peru", "A", _CROP,
       "ONG antitransgenicos"),
    _x("PE", "Temas Salud", "Salud con Lupa", "saludconlupa", "A", _B, "saludconlupa.com"),
    _x("PE", "Temas Agrarios", "Agraria.pe", "Agrariape", "A", _CROP, "agraria.pe"),
    _x("PE", "Temas Salud", "ALAFARPE", "Alafarpe", "A", _B, "gremio farmaceutico"),
    _x("PE", "Coyuntura Politica", "Ojo Publico", "Ojo_Publico", "B", _T, "ojo-publico.com"),
    _x("PE", "Coyuntura Politica", "Convoca", "convocape", "B", _T, "convoca.pe"),
    _x("PE", "Temas Tech", "Hiperderecho", "hiperderecho", "A", _TECH,
       "derechos digitales, datos, IA; activo 2026"),
    _x("PE", "Temas Tech", "Erick Iriarte (IALaw)", "coyotegris", "A", _TECH,
       "abogado datos personales / regulacion digital; activo 2026"),
    # --- PE: autoridades ---
    _x("PE", "Institucion", "Keiko Fujimori (Presidenta)", "KeikoFujimori", "A", _T,
       "Presidenta desde 28/07/2026"),
    _x("PE", "Institucion", "Luis Galarreta (PCM)", "luchogalarreta", "A", _T,
       "Presidente del Consejo de Ministros"),
    _x("PE", "Institucion", "Juan Sheput (Trabajo)", "JuanSheput", "B", _T,
       "Ministro de Trabajo, ve EsSalud"),
    _x("PE", "Temas Agrarios", "Vladimiro Huaroc (MINAM)", "VladimiroHuaroc", "A", _CROP,
       "Ministro del Ambiente"),
    _x("PE", "Temas Salud", "Susana Matute (Comision Salud Senado)", "MatuteCharun", "A", _B + _I,
       "Preside Comision de Salud y otras materias del Senado (El Peruano)"),
    _x("PE", "Institucion", "Oscar Reto (Pdte. Diputados)", "OscarReto62", "B", _T,
       "Presidente de la Camara de Diputados"),
    # --- PE: periodistas y seguimiento ---
    _x("PE", "Coyuntura Politica", "Graciela Villasis", "gvillasis", "A", _T,
       "Primicias Ejecutivo (adelanto renuncia de Boluarte)"),
    _x("PE", "Coyuntura Politica", "Juliana Oxenford", "julianaoxenford", "B", _T, "periodista"),
    _x("PE", "Coyuntura Politica", "Christopher Acosta", "TrujiYo", "B", _T, "investigacion Latina"),
    _x("PE", "Coyuntura Politica", "Marco Sifuentes", "ocram", "B", _T, "La Encerrona"),
    _x("PE", "Coyuntura Politica", "Augusto Alvarez Rodrich", "alvarezrodrich", "B", _T, "periodista"),
    _x("PE", "Coyuntura Politica", "Beto Ortiz", "PolloFarsantePe", "B", _T, "Willax"),
    _x("PE", "Coyuntura Politica", "Milagros Leiva (programa)", "MLEntrevista", "C", _T,
       "cuenta de su programa en Willax"),
    _x("PE", "Coyuntura Politica", "Diana Seminario", "Dianasemi", "A", _T, "Congreso, Canal N"),
    _x("PE", "Coyuntura Politica", "Cesar Romero", "CesarRomeroC", "A", _T,
       "editor general La Republica, Congreso"),
    _x("PE", "Coyuntura Politica", "Juan Carlos Tafur", "jctafur", "B", _T, "director Sudaca"),
    _x("PE", "Coyuntura Politica", "Daniel Yovera", "danielyovera", "B", _T, "Epicentro TV"),
    _x("PE", "Coyuntura Politica", "Nelly Luna Amancio", "nellylun", "A", _T + _CROP,
       "directora Ojo Publico, Congreso y ambiente"),
    _x("PE", "Coyuntura Politica", "Lima Gris", "Limagris", "C", _T,
       "adelanta nombramientos (adelanto el de Dyer en MINSA)"),
    _x("PE", "Temas Salud", "Fabiola Torres", "fabiolatorres", "A", _CROP,
       "directora Salud con Lupa: salud, farma y plaguicidas"),
    _x("PE", "Coyuntura Politica", "IPE", "ipeopinion", "B", _T, "actividad 2026 no confirmada"),
    _x("PE", "Coyuntura Politica", "Diego Macera (IPE)", "dmacera", "B", _T, "actividad 2026 no confirmada"),
    _x("PE", "Coyuntura Politica", "IEP", "IEPeruanos", "A", _T, "encuestas, Congreso"),
    _x("PE", "Coyuntura Politica", "Ipsos Peru", "ipsosperu", "B", _T, "encuestas"),
    _x("PE", "Coyuntura Politica", "Alfredo Torres (Ipsos)", "AlfredoMTorres", "B", _T, "encuestas"),
    _x("PE", "Coyuntura Politica", "Transparencia", "ACTransparencia", "B", _T, "observatorio civico"),
    _x("PE", "Coyuntura Politica", "Proetica", "ProeticaPeru", "B", _T, "anticorrupcion, designaciones"),
    _x("PE", "Coyuntura Politica", "Fernando Tuesta", "tuesta", "A", _T, "reforma politica, bicameralidad"),
    _x("PE", "Coyuntura Politica", "Eduardo Dargent", "DargentEduardo", "B", _T, "politologo PUCP"),
    _x("PE", "Coyuntura Politica", "Gonzalo Banda", "gonza_banda", "C", _T, "analista"),
    _x("PE", "Coyuntura Politica", "Politica La Republica", "Politica_LR", "A", _T, "gabinete, Congreso"),
    _x("PE", "Coyuntura Politica", "Canal N", "canalN_", "A", _T, "Congreso, Ejecutivo"),
    _x("PE", "Coyuntura Politica", "Infobae Peru", "infobaeperu", "A", _T, "Congreso, Ejecutivo"),
    _x("PE", "Coyuntura Politica", "Exitosa", "exitosape", "B", _T, "Congreso en vivo"),
    _x("PE", "Coyuntura Politica", "Peru21", "peru21noticias", "B", _T, "politica"),
    _x("PE", "Coyuntura Politica", "Willax TV", "willaxtv", "B", _T, "entrevistas a ministros"),
    _x("PE", "Coyuntura Politica", "N60 Noticias", "N60Noticias", "C", _T, "agregador"),
    _x("PE", "Coyuntura Politica", "Sudaca", "SudacaPeru", "C", _T, "medio digital"),

    # --- EC: instituciones ---
    _x("EC", "Institucion", "Presidencia Ecuador", "Presidencia_Ec", "A", _T, "decretos, Ejecutivo"),
    _x("EC", "Institucion", "Comunicacion Presidencia", "ComunicacionEc", "A", _T,
       "Secretaria General de Comunicacion"),
    _x("EC", "Institucion", "Asamblea Nacional", "AsambleaEcuador", "A", _T, "asambleanacional.gob.ec"),
    _x("EC", "Institucion", "TV Legislativa", "TvlEcuador", "A", _T, "plenos y comisiones en vivo"),
    _x("EC", "Institucion", "Corte Constitucional", "CorteConstEcu", "B", _T,
       "corteconstitucional.gob.ec"),
    _x("EC", "Institucion", "Registro Oficial", "RegistrOficial", "A", _T, "registroficial.gob.ec"),
    _x("EC", "Temas Salud", "Ministerio de Salud Publica", "Salud_Ec", "A", _B, "MSP"),
    _x("EC", "Temas Salud", "IESS", "IESSec", "B", _B, "iess.gob.ec"),
    _x("EC", "Temas Salud", "ARCSA", "Arcsa_Ec", "A", _B, "agencia sanitaria"),
    _x("EC", "Institucion", "SERCOP", "SERCOPec", "B", _B + _G, "compras publicas"),
    _x("EC", "Temas Agrarios", "DGAC Ecuador", "dgac_ecuador", "B", _CROP, "aviacion civil, drones"),
    # --- EC: gremios, ONG y medios ---
    _x("EC", "Temas Agrarios", "AEBE", "aebeecuador", "A", _CROP, "exportadores de banano"),
    _x("EC", "Temas Agrarios", "CONAIE", "CONAIE_Ecuador", "B", _CROP, "movimiento indigena"),
    _x("EC", "Temas Agrarios", "Mundo Agropecuario", "Munagropecuario", "B", _CROP, "agro, plagas"),
    _x("EC", "Temas Salud", "Edicion Medica", "edicionmedEC", "A", _B,
       "MSP, ARCSA, IESS, medicamentos; actividad 2026 no confirmada"),
    _x("EC", "Coyuntura Politica", "Primicias", "primicias", "A", _T, "primicias.ec"),
    _x("EC", "Coyuntura Politica", "Expreso", "expresoec", "B", _T, "expreso.ec"),
    _x("EC", "Coyuntura Politica", "El Universo", "eluniversocom", "B", _T, "eluniverso.com"),
    _x("EC", "Coyuntura Politica", "El Comercio EC", "elcomerciocom", "B", _T, "medio"),
    _x("EC", "Coyuntura Politica", "Vistazo", "revistavistazo", "B", _T, "vistazo.com"),
    _x("EC", "Coyuntura Politica", "Ecuavisa", "ecuavisa", "B", _T, "cuenta general"),
    _x("EC", "Coyuntura Politica", "Ecuavisa Informa", "EcuavisaInforma", "B", _T, "cuenta de noticias"),
    _x("EC", "Coyuntura Politica", "Teleamazonas", "teleamazonasec", "B", _T, "teleamazonas.com"),
    _x("EC", "Coyuntura Politica", "El Balance", "ElBalance_EC", "B", _T, "contratos publicos"),
    _x("EC", "Coyuntura Politica", "Politicamente Correcto", "politikcorrecta", "B", _T + _B,
       "programa Ecuavisa, ministros e IESS"),
    _x("EC", "Coyuntura Politica", "GK", "GKecuador", "B", _T, "politica, fiscal"),
    _x("EC", "Coyuntura Politica", "Plan V", "revistaPlanV", "B", _T, "investigacion"),
    _x("EC", "Coyuntura Politica", "RTP Ecuador", "RtpEcuador", "B", _T, "decretos, nombramientos"),
    _x("EC", "Coyuntura Politica", "Ecuadorinmediato", "ecuainm_oficial", "B", _T, "decretos #URGENTE"),
    _x("EC", "Temas Tech", "La Hora", "lahoraecuador", "B", _T + _TECH, "politica, datos personales"),
    _x("EC", "Coyuntura Politica", "El Dato Ec", "ElDatoEcua", "C", _T, "agregador de urgentes"),
    _x("EC", "Coyuntura Politica", "La Data", "ladataec", "C", _T, "agregador progobierno"),
    _x("EC", "Coyuntura Politica", "Tiempo Real", "TiempoRealEC", "C", _T, "decretos, avisos oficiales"),
    _x("EC", "Coyuntura Politica", "W Radio Ecuador", "WRadioEc", "C", _T, "decretos"),
    _x("EC", "Coyuntura Politica", "El Mercurio Manta", "elmercuriomanta", "C", _T, "Asamblea"),
    _x("EC", "Coyuntura Politica", "KCH Radio", "kchradio", "C", _T, "Asamblea, Ejecutivo"),
    _x("EC", "Coyuntura Politica", "La Radio Asamblea", "LaRadioAsamblea", "C", _T,
       "actividad 2026 no confirmada"),
    _x("EC", "Coyuntura Politica", "Analisis Semanal", "analisissemanal", "C", _T,
       "actividad 2026 no confirmada"),
    _x("EC", "Coyuntura Politica", "Participacion Ciudadana", "ParticipacionPC", "B", _T,
       "observacion democratica, Asamblea"),
    _x("EC", "Coyuntura Politica", "Grupo FARO", "FARO_org", "B", _T, "actividad 2026 no confirmada"),
    _x("EC", "Coyuntura Politica", "Fundamedios", "FUNDAMEDIOS", "B", _G, "libertad de prensa"),
    _x("EC", "Coyuntura Politica", "Ecuador Chequea", "ECUADORCHEQUEA", "B", _T, "verificador"),
    _x("EC", "Coyuntura Politica", "Lupa Media", "LupaMediaEC", "C", _T, "verificador"),
    # --- EC: autoridades ---
    _x("EC", "Institucion", "Daniel Noboa (Presidente)", "DanielNoboaOk", "A", _T, "Presidente"),
    _x("EC", "Institucion", "Mishel Mancheno (Pdta. Asamblea)", "mishelmanchenok", "A", _T,
       "Presidenta de la Asamblea desde 08/06/2026"),
    _x("EC", "Temas Agrarios", "Camila Leon (Comision Biodiversidad)", "camileonok", "A", _CROP,
       "preside Comision de Biodiversidad (ley de Bioeconomia)"),
    _x("EC", "Institucion", "Valentina Centeno (Comision Desarrollo Economico)", "ValenCenteno",
       "A", _T, "cargo confirmado hasta dic-2025, 2026 sin reconfirmar"),
    # --- EC: periodistas y seguimiento ---
    _x("EC", "Coyuntura Politica", "Janet Hinostroza", "janethinostroza", "A", _T,
       "primicias Ejecutivo"),
    _x("EC", "Coyuntura Politica", "Fabricio Vela", "fabriciovelav", "A", _T,
       "periodista legislativo, primicias"),
    _x("EC", "Coyuntura Politica", "Martin Pallares", "Martinminguchi", "B", _T, "Expreso / 4Pelagatos"),
    _x("EC", "Coyuntura Politica", "Lenin Artieda", "LeninArtieda", "B", _T, "Ecuavisa"),
    _x("EC", "Coyuntura Politica", "Arturo Torres", "Cascabelito09", "B", _T, "director Codigo Vidrio"),
    _x("EC", "Coyuntura Politica", "Codigo Vidrio", "CodigoVidrioEc", "B", _T, "investigacion"),
    _x("EC", "Coyuntura Politica", "Carlos Vera", "CarlosVerareal", "C", _T,
       "OJO: existe clon @CarlosVerareaI (I mayuscula)"),
    _x("EC", "Coyuntura Politica", "Andersson Boscan", "AnderssonBoscan", "C", _T, "periodista"),
    _x("EC", "Coyuntura Politica", "Carlos Rojas Araujo", "carlosrojasecu", "A", _T + _B,
       "director Politicamente Correcto, politica y salud"),
    _x("EC", "Coyuntura Politica", "Alvaro Espinosa", "alvatin18", "A", _T,
       "director El Balance, adelanta nombramientos"),
    _x("EC", "Coyuntura Politica", "Andrea Orbe", "AndreaOrbe5", "B", _T, "radio Quito, Ejecutivo"),
    _x("EC", "Coyuntura Politica", "Sara Ortiz", "saritortiz", "B", _T, "Expreso, investigacion"),
    _x("EC", "Coyuntura Politica", "Monica Velasquez", "MoniVelasquezV", "C", _T, "investigacion"),
    _x("EC", "Coyuntura Politica", "Alondra Santiago", "cubalondra", "C", _T, "periodista"),
    _x("EC", "Coyuntura Politica", "Alberto Acosta-Burneo", "ALBERTOACOSTAB", "B", _T,
       "editor Analisis Semanal, economia"),
    _x("EC", "Coyuntura Politica", "Ximena Ron Erraez", "XRonErraez", "B", _T,
       "analista constitucional, sigue a la Corte"),
]


def all_fuentes() -> list[dict]:
    fuentes = FUENTES_PE + FUENTES_EC + FUENTES_GOOGLE_NEWS + FUENTES_X_2026
    for f in fuentes:
        f.setdefault("clientes", _clientes_de(f))
    return fuentes
