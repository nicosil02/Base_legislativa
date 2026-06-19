"""Catalogo de fuentes de noticias (Peru + Ecuador).

Cada fuente es un dict: categoria, pais, nombre, url, rss_url, tipo, notas.

Tipos (los maneja noticias/scraper.py:fetch_fuente):
  - gobpe:  instituciones del portal gob.pe -> API busquedas.json (noticias +
            normas). El slug sale del path de `url`. Trae normas SOLO si la
            categoria es Salud/Agrario/KYC (reguladores) — el resto seria ruido.
  - rss:    feed RSS/Atom. Si `rss_url` falla o esta vacio, el scraper hace
            autodiscovery (<link rss> o /feed/) desde `url` y se auto-sana.
  - html:   scraping HTML heuristico (sitios sin feed).
  - manual: catalogado pero sin scraping (redes sociales sin web propia, sitios
            caidos, o ya cubierto por otro modulo). No se scrapea.

Origen: "Matriz de Monitoreo - PL's.xlsx" (hojas Links_interes / Ecuador AN),
auditada fuente por fuente (jun 2026). Chile queda fuera (proyecto Cono Sur).

Para corregir una URL sin tocar este archivo:
  python -m noticias.cli set-url --pais PE --nombre "Gestion" --rss "https://..."
"""

# ============================================================
# PERU
# ============================================================
FUENTES_PE: list[dict] = [
    # --- COYUNTURA POLITICA: medios (RSS) ---
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "El Comercio",
     "url": "https://elcomercio.pe/politica/",
     "rss_url": "https://elcomercio.pe/arcio/rss/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Gestion",
     "url": "https://gestion.pe/politica/",
     "rss_url": "https://gestion.pe/arcio/rss/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "La Republica",
     "url": "https://larepublica.pe/politica", "tipo": "html"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Peru 21",
     "url": "https://peru21.pe/politica/",
     "rss_url": "https://peru21.pe/feed/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "RPP",
     "url": "https://rpp.pe/politica",
     "rss_url": "https://rpp.pe/rss", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "PE", "nombre": "Bloomberg en Linea",
     "url": "https://www.bloomberglinea.com/latinoamerica/peru/",
     "rss_url": "https://www.bloomberglinea.com/arc/outboundfeeds/rss/?outputType=xml",
     "tipo": "rss"},

    # --- INSTITUCION: gob.pe (API JSON) ---
    {"categoria": "Institucion", "pais": "PE", "nombre": "PCM",
     "url": "https://www.gob.pe/institucion/pcm/noticias", "tipo": "gobpe",
     "notas": "Presidencia del Consejo de Ministros"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Presidencia",
     "url": "https://www.gob.pe/institucion/presidencia/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Ministerio de Relaciones Exteriores",
     "url": "https://www.gob.pe/institucion/rree/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MEF",
     "url": "https://www.gob.pe/institucion/mef/noticias", "tipo": "gobpe",
     "notas": "Ministerio de Economia y Finanzas"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MINEDU",
     "url": "https://www.gob.pe/institucion/minedu/noticias", "tipo": "gobpe"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MINCETUR",
     "url": "https://www.gob.pe/institucion/mincetur/noticias", "tipo": "gobpe",
     "notas": "Comercio exterior, turismo, casinos/apuestas"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "MTC",
     "url": "https://www.gob.pe/institucion/mtc/noticias", "tipo": "gobpe",
     "notas": "Transportes y Comunicaciones"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "INDECOPI",
     "url": "https://www.gob.pe/institucion/indecopi/noticias", "tipo": "gobpe"},

    # --- INSTITUCION: portales propios / ya cubiertos ---
    {"categoria": "Institucion", "pais": "PE", "nombre": "Congreso - Proyectos de Ley",
     "url": "https://wb2server.congreso.gob.pe/spley-portal/", "tipo": "manual",
     "notas": "Cubierto por modulo scraper/ (API formal)"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "Agenda del Congreso",
     "url": "https://comunicaciones.congreso.gob.pe/agenda/", "tipo": "manual",
     "notas": "Cubierto por modulo mesas_tecnicas/ y sesiones/"},
    {"categoria": "Institucion", "pais": "PE", "nombre": "El Peruano - Normas Legales",
     "url": "https://diariooficial.elperuano.pe/normas", "tipo": "manual",
     "notas": "SPA Angular, HTML no scrapeable. Normas via gob.pe (reguladores)"},

    # --- TEMAS AGRARIOS (crop) ---
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "MIDAGRI",
     "url": "https://www.gob.pe/institucion/midagri/noticias", "tipo": "gobpe",
     "notas": "Desarrollo Agrario y Riego (+ normas)"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "PRODUCE",
     "url": "https://www.gob.pe/institucion/produce/noticias", "tipo": "gobpe",
     "notas": "Produccion / pesca (+ normas)"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "MINAM",
     "url": "https://www.gob.pe/institucion/minam/noticias", "tipo": "gobpe",
     "notas": "Ambiente (+ normas)"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "SENASA",
     "url": "https://www.gob.pe/institucion/senasa/noticias", "tipo": "gobpe",
     "notas": "Sanidad agraria (+ normas) — clave para crop"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Agraria.pe",
     "url": "https://agraria.pe/", "tipo": "html",
     "notas": "Posible JS-render; cobertura parcial"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CONVEAGRO",
     "url": "https://conveagro.org.pe/",
     "rss_url": "https://conveagro.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "AGAP",
     "url": "https://agapperu.org/",
     "rss_url": "https://agapperu.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CAP",
     "url": "https://cap.org.pe/",
     "rss_url": "https://cap.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "Sociedad Peruana de Derecho Ambiental",
     "url": "https://spda.org.pe/",
     "rss_url": "https://spda.org.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "PE", "nombre": "CEPES",
     "url": "https://www.cepes.org.pe/", "tipo": "manual",
     "notas": "Sitio no responde (jun 2026); revisar si vuelve"},

    # --- TEMAS SALUD (farma) ---
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Ministerio de Salud",
     "url": "https://www.gob.pe/institucion/minsa/noticias", "tipo": "gobpe",
     "notas": "MINSA (+ normas). Cubre DIGEMID via keyword en normas"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Colegio de Quimicos Farmaceuticos del Peru",
     "url": "https://cqfp.pe/",
     "rss_url": "https://cqfp.pe/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Esperantra",
     "url": "https://esperantra.org/",
     "rss_url": "https://esperantra.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "DIGEMID",
     "url": "https://www.digemid.minsa.gob.pe/webDigemid/", "tipo": "manual",
     "notas": "Subdominio MINSA, sin slug gob.pe. Normas DIGEMID llegan via MINSA"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Lazo Rosado",
     "url": "https://twitter.com/LazoRosadoPeru", "tipo": "manual",
     "notas": "Solo X/Twitter; sin web propia"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Voces Ciudadanas",
     "url": "https://www.facebook.com/VocesCiudadanas", "tipo": "manual",
     "notas": "Solo Facebook; web caida"},
    {"categoria": "Temas Salud", "pais": "PE", "nombre": "Federacion Peruana de Enfermedades Raras",
     "url": "https://www.facebook.com/enfermedadesrarasperu/", "tipo": "manual",
     "notas": "Solo Facebook; sin web rastreable"},

    # --- TEMAS TECH ---
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "OSIPTEL",
     "url": "https://www.gob.pe/institucion/osiptel/noticias", "tipo": "gobpe",
     "notas": "Regulador telecom"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Hiperderecho",
     "url": "https://hiperderecho.org/",
     "rss_url": "https://hiperderecho.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Asociacion Latinoamericana de Internet",
     "url": "https://alai.lat/",
     "rss_url": "https://alai.lat/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "DPL News Peru",
     "url": "https://dplnews.com/tag/peru/",
     "rss_url": "https://dplnews.com/feed/", "tipo": "rss",
     "notas": "Feed global; filtrar Peru en UI"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Niubox Legal",
     "url": "https://niubox.legal/blog/", "tipo": "html"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Comex Peru",
     "url": "https://www.comexperu.org.pe/", "tipo": "html",
     "notas": "Posible JS-render; cobertura parcial"},
    {"categoria": "Temas Tech", "pais": "PE", "nombre": "Ebiz Latam",
     "url": "https://ebiz.pe/noticias/", "tipo": "html"},

    # --- TEMAS KYC / AML ---
    {"categoria": "Temas KYC/AML", "pais": "PE", "nombre": "SBS - Resoluciones",
     "url": "https://www.sbs.gob.pe/normativa/normativa-sbs", "tipo": "html",
     "notas": "Superintendencia de Banca y Seguros; portal propio, cobertura parcial"},
]


# ============================================================
# ECUADOR  (gob.ec son WordPress -> /feed/ RSS)
# ============================================================
FUENTES_EC: list[dict] = [
    # --- COYUNTURA POLITICA: medios ---
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "El Comercio",
     "url": "https://www.elcomercio.com/",
     "rss_url": "https://www.elcomercio.com/feed/", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "El Universo",
     "url": "https://www.eluniverso.com/noticias/politica/",
     "rss_url": "https://www.eluniverso.com/arc/outboundfeeds/rss/?outputType=xml",
     "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "PRIMICIAS",
     "url": "https://www.primicias.ec/politica/", "tipo": "html"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Gestion",
     "url": "https://www.revistagestion.ec/",
     "rss_url": "https://revistagestion.primicias.ec/index.xml", "tipo": "rss"},
    {"categoria": "Coyuntura Politica", "pais": "EC", "nombre": "Bloomberg Linea Ecuador",
     "url": "https://www.bloomberglinea.com/latinoamerica/ecuador/",
     "rss_url": "https://www.bloomberglinea.com/arc/outboundfeeds/rss/?outputType=xml",
     "tipo": "rss"},

    # --- INSTITUCION ---
    {"categoria": "Institucion", "pais": "EC", "nombre": "Registro Oficial",
     "url": "https://www.registroficial.gob.ec/",
     "rss_url": "https://www.registroficial.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Portal de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/es",
     "rss_url": "https://www.asambleanacional.gob.ec/es/rss.xml", "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Ministerio de Economia y Finanzas",
     "url": "https://www.finanzas.gob.ec/",
     "rss_url": "https://www.finanzas.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Asamblea Nacional - Proyectos de Ley",
     "url": "https://leyes.asambleanacional.gob.ec/", "tipo": "manual",
     "notas": "Cubierto por modulo scraper_ec/"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Agenda de la Asamblea Nacional",
     "url": "https://www.asambleanacional.gob.ec/es/agenda_de_comunicacion",
     "tipo": "manual", "notas": "Cubierto por modulo agenda_ec/"},
    {"categoria": "Institucion", "pais": "EC", "nombre": "Decretos Presidenciales",
     "url": "https://minka.presidencia.gob.ec/portal/usuarios_externos.jsf",
     "tipo": "manual", "notas": "Portal con login (HTTP 403 al scrapear)"},

    # --- TEMAS AGRARIOS (crop) ---
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "Ministerio de Agricultura y Ganaderia",
     "url": "https://www.agricultura.gob.ec/noticias/",
     "rss_url": "https://www.agricultura.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "Ministerio de Produccion Comercio Exterior",
     "url": "https://www.produccion.gob.ec/noticias/",
     "rss_url": "https://www.produccion.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "AGROCALIDAD",
     "url": "https://www.agrocalidad.gob.ec/category/noticias/",
     "rss_url": "https://www.agrocalidad.gob.ec/feed/", "tipo": "rss",
     "notas": "Regulacion fito/zoosanitaria — clave para crop"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "Ministerio del Ambiente",
     "url": "https://www.ambiente.gob.ec/noticias/",
     "rss_url": "https://www.ambiente.gob.ec/feed/", "tipo": "rss",
     "notas": "Puede dar error SSL intermitente"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "INIAP",
     "url": "https://www.iniap.gob.ec/noticias/",
     "rss_url": "https://www.iniap.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "Observatorio de Cambio Rural",
     "url": "https://ocaru.org.ec/",
     "rss_url": "https://ocaru.org.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "El Productor",
     "url": "https://elproductor.com/",
     "rss_url": "https://elproductor.com/feed/", "tipo": "rss",
     "notas": "Puede bloquear scraping (Cloudflare 403)"},
    {"categoria": "Temas Agrarios", "pais": "EC", "nombre": "CONAIE",
     "url": "https://conaie.org/", "tipo": "manual",
     "notas": "Sitio no responde establemente; publica en X"},

    # --- TEMAS SALUD (farma) ---
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "ARCSA (Regulacion Sanitaria)",
     "url": "https://www.controlsanitario.gob.ec/noticias/",
     "rss_url": "https://www.controlsanitario.gob.ec/feed/", "tipo": "rss",
     "notas": "Agencia de regulacion sanitaria — clave para farma"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Ministerio de Salud Publica",
     "url": "https://www.salud.gob.ec/",
     "rss_url": "https://www.salud.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "IESS (Seg. Social)",
     "url": "https://www.iess.gob.ec/",
     "rss_url": "https://www.iess.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "ALAFAR Ecuador",
     "url": "https://www.alafar.org/",
     "rss_url": "https://www.alafar.org/feed/", "tipo": "rss",
     "notas": "Asociacion de laboratorios farmaceuticos"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "SOLCA Ecuador",
     "url": "https://www.solca.med.ec/",
     "rss_url": "https://www.solca.med.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Pacientes Ecuador",
     "url": "https://pacientesecuador.org/noticias/",
     "rss_url": "https://pacientesecuador.org/feed/", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Edicion Medica",
     "url": "https://www.edicionmedica.ec/",
     "rss_url": "https://www.edicionmedica.ec/rss", "tipo": "rss"},
    {"categoria": "Temas Salud", "pais": "EC", "nombre": "Jovenes Contra el Cancer Ecuador",
     "url": "https://twitter.com/jcontraelcancer", "tipo": "manual",
     "notas": "Solo X; sin web rastreable"},

    # --- TEMAS TECH / KYC ---
    {"categoria": "Temas KYC/AML", "pais": "EC", "nombre": "Superintendencia de Proteccion de Datos",
     "url": "https://spdp.gob.ec/",
     "rss_url": "https://spdp.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas KYC/AML", "pais": "EC", "nombre": "Ministerio de Telecomunicaciones",
     "url": "https://www.telecomunicaciones.gob.ec/category/catactualidad/",
     "rss_url": "https://www.telecomunicaciones.gob.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "DPL News Ecuador",
     "url": "https://dplnews.com/tag/ecuador/",
     "rss_url": "https://dplnews.com/feed/", "tipo": "rss",
     "notas": "Feed global; filtrar Ecuador en UI"},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Forbes Digital Ecuador",
     "url": "https://www.forbes.com.ec/",
     "rss_url": "https://www.forbes.com.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Camara Ecuatoriana de Comercio Exterior",
     "url": "https://cece.ec/blog/",
     "rss_url": "https://cece.ec/feed/", "tipo": "rss"},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Criptonoticias",
     "url": "https://www.criptonoticias.com/etiquetas/bitcoin-ecuador/",
     "rss_url": "https://www.criptonoticias.com/feed/", "tipo": "rss",
     "notas": "Puede bloquear scraping (403)"},
    {"categoria": "Temas Tech", "pais": "EC", "nombre": "Camara de Innovacion y Tecnologia Ecuatoriana",
     "url": "https://www.facebook.com/CamaraCITEC/", "tipo": "manual",
     "notas": "Solo Facebook; web no responde"},
]


def all_fuentes() -> list[dict]:
    return FUENTES_PE + FUENTES_EC
