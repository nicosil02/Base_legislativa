"""Clasificacion tematica de noticias por keywords en titulo+resumen.

5 temas finales (consolidados):
  - Coyuntura politica
  - Salud (incluye farma/medicamentos)
  - Tech / Digital
  - Crop (agro)
  - KYC / AML / Financiero

ADEMAS un flag transversal `es_normativa`: si la noticia menciona decreto,
resolucion, ley, reglamento, registro oficial, normas legales, etc. la
marcamos como normativa (badge en UI). Esto aparece como tag adicional,
NO como categoria propia: una "ley de proteccion de datos" aparece bajo
Tech/Digital con el badge Normativa.
"""
from __future__ import annotations

import re

from clientes import config as _clientes
from core.text import norm as _norm


TEMAS: dict[str, list[str]] = {
    "Coyuntura política": [
        # Instituciones y roles del poder (relevantes cuando el foco es
        # política; asumimos que el usuario prefiere cobertura amplia).
        "presidente", "presidenta", "vicepresidente", "vicepresidenta",
        # "premier" solo matcheaba "Premier League".
        "premier peruano", "premier del peru", "gabinete", "consejo de ministros",
        "ministro", "ministra", "congreso", "asamblea nacional",
        "fiscal", "fiscalía", "fiscalia", "fiscal de la nación",
        "diputado", "diputada", "senador", "senadora",
        "ejecutivo", "legislativo", "PCM",
        # Procesos políticos
        "vacancia", "interpelacion", "interpelación",
        "moción de censura", "denuncia constitucional",
        "cambio de gabinete", "juramentación", "juramentacion",
        "oposición", "oposicion", "oficialismo",
        "elecciones", "comicios", "campaña electoral",
        "JNE", "ONPE", "RENIEC", "CNE",
        "candidato", "candidata",
        "partido político", "partido politico",
        # Gobierno actual PE (Keiko Fujimori 2026-2031, gabinete Galarreta).
        # Cuando cambie, actualizar acá.
        # "Keiko" sola matcheaba a la orca de "Free Willy".
        "Keiko Fujimori", "Fujimori",
        "Fuerza Popular",
        "Galarreta",   # premier
        # Ministros del gabinete Galarreta (apellidos únicos)
        "Espá",         # RREE
        "Belaúnde Llosa",  # Defensa
        "Elmer Cuba", "Cuba Bustinza",  # MEF
        "Astudillo",   # Interior
        "Álvarez Miranda", "Alvarez Miranda",  # Justicia
        "Chang Escobedo",  # Educación
        "Sheput",      # Trabajo
        "Requejo",     # Producción
        "Shinno",      # Energía y Minas
        "Rafael Rey",  # MTC
        "Arnillas",    # Vivienda
        "Seminario Marón",  # Mujer
        "Beingolea",   # Cultura
        "Canales Martínez",  # MIDIS
        # EC actual
        "Noboa",
    ],
    "Salud": [
        # Sistema de salud / instituciones
        "hospital", "paciente", "enfermedad", "epidemia", "brote",
        "MINSA", "MSP", "ESSALUD", "IESS", "SIS", "SOLCA",
        "atencion medica", "atención médica", "atencion primaria",
        "cobertura sanitaria", "sistema de salud", "emergencia sanitaria",
        # Padecimientos
        "cancer", "cáncer", "diabetes", "tuberculosis", "dengue",
        "covid", "salud mental",
        # Farma (consolidado dentro de Salud)
        "medicamento", "medicamentos", "vacuna", "vacunación",
        # "medicina" solo en plural: el singular trae la carrera de Medicina.
        "medicinas", "fármaco", "fármacos",
        "vacunacion", "antibiótico", "antibiotico", "laboratorio",
        "farmaceutica", "farmacéutica", "industria farma",
        "ARCSA", "DIGEMID", "ANVISA", "FDA", "EMA",
        "biosimilar", "biotecnología", "biotecnologia",
        "ensayo clinico", "ensayo clínico", "patente farmacéutica",
        "registro sanitario", "DCI", "principio activo",
        "esperantra", "lazo rosado", "alafar", "ALAFAR",
        "pacientes ecuador", "edicion medica", "edición médica",
        "enfermedades raras", "FEPPER",
        # Ministro de Salud actual (gabinete Galarreta)
        "Luis Dyer", "Dyer Fernández", "Dyer Fernandez",
        # "salud" a secas va aparte, solo en el titulo (_SALUD_EN_TITULO).
        "telemedicina", "hepatitis", "infeccion", "farmacia",
        "botica", "brigada medica", "brigadas medicas", "vigilancia sanitaria",
    ],
    "Tech / Digital": [
        # "digital" suelta no: "se transmitia por plataformas digitales", "su
        # nueva etapa digital" (medios) metian ~150 notas cada 2 semanas.
        # Solo en frase, ver _EXTRA_REGEX.
        "tecnología", "tecnologia", "ciberseguridad",
        "datos personales", "proteccion de datos", "protección de datos",
        "inteligencia artificial", "fintech", "criptomoneda",
        "criptomonedas", "cripto", "bitcoin", "blockchain",
        "telecomunicaciones", "OSIPTEL", "ARCOTEL", "SPDP",
        "5G", "internet", "ciberataque", "hackeo", "phishing",
        "fraude digital", "ecommerce", "comercio electrónico",
        "comercio electronico", "neutralidad de red",
        "transformación digital", "transformacion digital",
        # Sin "INDECOPI": casi nunca es digital (antidumping, multas).
        "Niubox", "Hiperderecho", "ALAI",
        # "IA" en mayuscula queda exacta y no choca con "dia".
        "telemedicina", "cibernetico", "cibernetica",
        "digitalizacion", "dinero electronico", "firma electronica",
        "fibra optica", "banda ancha", "IA",
        "MinTel", "DPL", "Forbes Digital", "CECE",
        # Autoridad de datos PE (MINJUS/MINJUSDH)
        "ANPD", "APDP", "MINJUS", "MINJUSDH",
        "DGTAIPD",           # nombre viejo, sigue apareciendo
        "Ley 29733", "Ley Nº 29733",
        "oficial de protección de datos", "oficial de proteccion de datos",
        "ODP",
        "bancodatos",
        "sanción ANPD", "sancion ANPD", "multa ANPD",
        "procedimiento sancionador",
        # Gobierno digital PE (dentro de PCM)
        "SGTD", "Secretaría de Gobierno Digital",
        "Secretaria de Gobierno Digital",
        "Secretaría de Gobierno y Transformación Digital",
        "Secretaria de Gobierno y Transformacion Digital",
        # El nombre de un ministro no es proxy del tema ("Rogers Valencia"
        # era todo turismo). ponytail: "Álvarez Miranda" (Justicia, ANPD)
        # tiene el mismo riesgo; sacarlo si empieza a traer ruido.
        "Álvarez Miranda", "Alvarez Miranda",
    ],
    "Crop": [
        "agricultura", "agrícola", "agricola", "agropecuario",
        "agropecuaria", "ganaderia", "ganadería", "semilla",
        "semillas", "riego", "siembra", "cosecha", "agroexport",
        "agroexportación", "agroexportacion", "MIDAGRI", "SENASA",
        # Sin "ANA" (Autoridad Nacional del Agua): matchea el nombre "Ana".
        "AGROCALIDAD", "agrario", "conveagro", "CONVEAGRO",
        "AGAP", "CEPES", "agraria.pe", "transgénicos", "transgenicos",
        "OGM", "fertilizantes", "campesino", "campesina", "agro",
        "INIAP", "MAG", "MAGAP", "produccion agropecuaria",
        "producción agropecuaria",
        # Agroquimicos
        "plaguicida", "plaguicidas", "pesticida", "pesticidas",
        "agroquímico", "agroquimico", "agroquímicos", "agroquimicos",
        "glifosato", "herbicida", "herbicidas", "insecticida", "insecticidas",
        "fungicida", "fungicidas",
        # Notas de campo ("hectáreas de cultivos", "ganaderos"); plurales via _compile.
        "cultivo", "ganadero", "ganadera", "maiz", "agroecologia",
        "fitosanitario", "fitosanitaria", "agroindustria", "agroindustrial",
        # Ministros actuales de sector (gabinete Galarreta)
        "Vinelli",     # MIDAGRI (agro)
        "Huaroc",      # MINAM (ambiente)
    ],
    "KYC / AML / Financiero": [
        "lavado de activos", "prevención de lavado",
        "prevencion de lavado", "antilavado", "anti-lavado",
        "financiamiento del terrorismo", "PEP", "UIF",
        "SBS", "UAF", "due diligence", "GAFI", "GAFILAT",
        "FinCEN", "compliance financiero", "compliance",
        "AFP", "ONP", "SUNAT", "SRI",
        # "tributo" singular tambien es homenaje; el plural es siempre fiscal.
        "tributos", "impuesto",
        # "fiscal" sola tambien es la Fiscalia ("carpeta fiscal"): solo frases.
        "evasión fiscal", "evasion fiscal", "régimen tributario",
        "regimen tributario",
        "superintendencia de banca", "banca y seguros",
        "lavado", "activos ilícitos", "activos ilicitos",
        # "pagos" a secas no ("pagos a docentes"). "bancos" va en _EXTRA_REGEX.
        "financiero", "financiera",
        "dinero electronico", "billetera digital", "billeteras digitales",
        "pagos digitales", "pago digital", "medios de pago", "sistema de pagos",
        "ecosistema de pagos", "pagos electronicos", "finanzas abiertas", "fintech",
        # Fraude de identidad: el negocio de Incode.
        "suplantación de identidad", "suplantacion de identidad",
        "fraude bancario", "fraude financiero",
    ],
}

# Keywords que necesitan un "no seguido de" (sentido figurado/homonimo) -
# se suman al patron del tema tal cual, sobre texto ya normalizado.
_EXTRA_REGEX: dict[str, list[str]] = {
    # "redes sociales" solo como objeto de regulacion: "lo compartio en sus
    # redes sociales" (farandula, sucesos) era la mayoria en la semana real.
    "Tech / Digital": [
        r"(?:menores|regula\w*|prohib\w*|ley|plataformas?)\W+(?:\w+\W+){0,4}redes sociales"
        r"|redes sociales\W+(?:\w+\W+){0,4}(?:menores|regula\w*|prohib\w*|ley)\b",
        r"\b(?:economia|derechos?|autoridad nacional|gobierno|fraudes?|estafas?|educacion|"
        r"alfabetizacion|habilidades|negocios?|servicios?|infraestructura|agenda|cedulas?|"
        r"identidad|firmas?|llave|billeteras?|pagos?|banca|comercio|transformacion|brecha|"
        r"ciudadania|soberania|seguridad|proteccion|violencia|acoso|amenaza|adiccion|ecosistema|"
        r"activos?|monedas?|dolar|euro|mercados?|publicidad|impuestos?|dni|documentos?|inclusion|"
        r"empresas?|bancos?|entidad(?:es)? financieras?|dinero|creditos?|transacciones|tramites?|"
        r"salud|apuestas) digital(?:es)?\b|\b100 ?% digital"],
    # Solo "bancos" (el sector): el singular es Banco Mundial/BID/Central.
    "KYC / AML / Financiero": [
        r"\bbancos\b(?! de (?:sangre|alimentos|leche|germoplasma|semillas|"
        r"datos|ojos|tejidos|preguntas|proyectos|arena|niebla|peces|habitat)|"
        r" comunitarios)"],
    # "ganado" sustantivo, no participio ("tras haber ganado en Pekin" era
    # Crop): solo con articulo/"de" delante o con el tipo de ganado detras.
    "Crop": [r"\b(?:el|del|de|al|su|sus|los) ganados?\b"
             r"|\bganados? (?:vacuno|bovino|ovino|caprino|lechero|porcino|de carne)"],
    # "influenza aviar" es sanidad animal (ya cae en Crop via SENASA/aves).
    # ("salud" a secas va aparte, solo en titulo: ver _SALUD_EN_TITULO.)
    "Salud": [r"\binfluenza\b(?! aviar)"],
}


# Keywords para badge transversal "Normativa": una noticia es marcada
# como normativa si menciona estos terminos (independiente del tema).
KEYWORDS_NORMATIVA = [
    "decreto supremo", "decreto legislativo", "decreto de urgencia",
    "decreto urgencia", "decreto presidencial", "decreto",
    "resolución ministerial", "resolucion ministerial",
    "resolución directoral", "resolucion directoral",
    "resolución suprema", "resolucion suprema",
    "acuerdo ministerial", "ley aprobada", "promulgación",
    "promulgacion", "publicada en el peruano", "el peruano publica",
    "normas legales", "registro oficial", "diario oficial",
    "reglamento", "norma técnica", "norma tecnica",
    "proyecto de ley", "proyecto normativo", "consulta pública",
    "consulta publica", "modificación reglamentaria",
    "modificacion reglamentaria", "circular sbs",
    "resolución sbs", "resolucion sbs", "resolución arcsa",
    "resolución digemid", "resolucion digemid",
]


def _compile(kws: list[str], plural: bool = False,
             extra: list[str] | None = None) -> re.Pattern:
    """plural=True: una palabra suelta en minuscula de 4+ letras acepta
    tambien su plural ("digital" -> "digitales"). Siglas y nombres propios
    (con mayuscula en la lista: SIS, MAG, Noboa) quedan exactos. Las frases
    ya matchean como substring."""
    alts = []
    for kw in kws:
        n = _norm(kw)
        if " " in n:
            alts.append(re.escape(n))
        elif plural and kw == kw.lower() and len(n) >= 4 and n.isalpha():
            alts.append(rf"\b{re.escape(n)}(?:e?s)?\b")
        else:
            alts.append(rf"\b{re.escape(n)}\b")
    return re.compile("|".join(alts + (extra or [])), re.IGNORECASE)


# Temas que trae la ficha de un cliente (clientes/<slug>/cliente.json,
# "temas_propios"): un cliente nuevo de otro rubro no necesita tocar TEMAS.
def _sumar_temas_propios() -> None:
    for tema, kws in _clientes.temas_propios().items():
        TEMAS[tema] = [*TEMAS.get(tema, []), *kws]


_sumar_temas_propios()
_PATTERNS = {tema: _compile(kws, plural=True, extra=_EXTRA_REGEX.get(tema))
             for tema, kws in TEMAS.items()}
_PATTERN_NORMATIVA = _compile(KEYWORDS_NORMATIVA)

# El digest descarta la normativa; esta lista rescata las normas que tocan
# el foco de los clientes. Se mira la DESCRIPCION de la norma, nunca la
# entidad: "Direccion General de Medicamentos" como emisor hacia pasar
# viajes y designaciones.
KEYWORDS_NORMA_INTERES = [
    # Incode / Google
    "datos personales", "proteccion de datos", "biometria", "biometrico",
    "biometrica", "biometricos", "biometricas", "identidad digital",
    "cedula digital", "dni electronico", "firma electronica", "firma digital",
    "inteligencia artificial", "ciberseguridad", "gobierno digital",
    "comercio electronico", "servicios digitales", "plataformas digitales",
    # Bayer / Syngenta (agro)
    "plaguicida", "plaguicidas", "fitosanitario", "fitosanitaria",
    "fitosanitarios", "agroquimico", "agroquimicos", "semillas", "transgenicos",
    "organismos vivos modificados", "fertilizantes", "bioinsumos",
    # Bayer (salud)
    "medicamentos", "productos farmaceuticos", "dispositivos medicos",
    "registro sanitario",
]
# Mas las "palabras_norma" de cada ficha de cliente.
KEYWORDS_NORMA_INTERES += [kw for kws in _clientes.campo("palabras_norma").values() for kw in kws]
_PATTERN_NORMA_INTERES = _compile(KEYWORDS_NORMA_INTERES)
# Tramite interno que menciona el tema de pasada.
_PATTERN_NORMA_TRAMITE = re.compile(
    r"^(designan|autorizan viaje|aceptan renuncia|encargan|dan por conclu|"
    r"se designa|se autoriza el viaje|se acepta la renuncia|"
    r"se encarga|conformar la comision|conforman la comision|"
    r"se autoriza una modificacion presupuestaria|otorgan licencia|"
    r"se otorga licencia)", re.IGNORECASE)


def es_norma_de_interes(descripcion: str | None) -> bool:
    """True si la descripcion de UNA norma (sin la entidad emisora) toca el
    foco de algun cliente y no es tramite administrativo."""
    d = _norm(descripcion)
    return bool(d) and not _PATTERN_NORMA_TRAMITE.match(d) \
        and bool(_PATTERN_NORMA_INTERES.search(d))


def es_normativa_de_interes(tags: str | None, resumen: str | None) -> bool:
    """Para una fila de `noticias` ya marcada normativa: ¿toca a un cliente?
    Compartido por el digest de WhatsApp y el correo diario. RO EC ya viene
    marcado por su scraper (su resumen es el indice entero, no una norma);
    El Peruano trae 1 norma por fila y su resumen es la descripcion."""
    t = tags.split("|") if isinstance(tags, str) else []
    if "registro-oficial" in t:
        return "interes-cliente" in t
    return es_norma_de_interes(resumen)


# "presidente" matchea igual al de un club de futbol: clasificar() saca
# Coyuntura política y Salud si el texto es de futbol.
KEYWORDS_DEPORTES = [
    "liga ecuabet", "liga pro", "copa sudamericana", "copa libertadores",
    "cuadrangular", "hexagonal", "hinchas", "hinchada", "estadio",
    "futbolista", "futbolistas", "delantero", "defensor", "arquero",
    "director tecnico", "director técnico", "barcelona sc", "emelec",
    # "IESS le certificó a FEF..." salia como Salud.
    "FEF", "ascenso nacional",
]
_PATTERN_DEPORTES = _compile(KEYWORDS_DEPORTES)


# Secciones del medio que nunca son foco (internacional, deportes): El
# Universo/El Comercio no son multipais y el filtro de pais no las toca.
KEYWORDS_SECCION_FUERA_URL = ["/internacional/", "/mundo/", "/deportes/", "/futbol/"]


def es_seccion_fuera_de_foco(url: str | None) -> bool:
    u = url.lower() if isinstance(url, str) else ""
    return any(k in u for k in KEYWORDS_SECCION_FUERA_URL)


def es_normativa_tag(tags: str | None) -> bool:
    """El Peruano / Registro Oficial taggean pipe-joined ("...|normativa"),
    los feeds gobpe usan "normas"."""
    t = tags.split("|") if isinstance(tags, str) else []
    return "normas" in t or "normativa" in t


# Farandula que nombra una enfermedad de pasada no es Salud. La señal es la
# seccion en la URL ("/afull/" es la de entretenimiento de El Comercio), no
# el texto.
KEYWORDS_ESPECTACULOS_URL = [
    "/entretenimiento/", "/farandula/", "/espectaculos/", "/afull/",
    "/gente/", "/cine/",
]


def es_espectaculos(url: str | None) -> bool:
    """True si la URL es de una seccion de entretenimiento/farandula."""
    if not url:
        return False
    return any(marca in url.lower() for marca in KEYWORDS_ESPECTACULOS_URL)


def clasificar(titulo: str | None, resumen: str | None = None,
               url: str | None = None) -> list[str]:
    """Lista de temas detectados en el contenido. Orden estable."""
    texto = _norm(_sin_homonimos(titulo, resumen))
    if not texto.strip():
        return []
    texto = _FRASES_NEUTRAS.sub(" ", texto)
    if _SENASA_DOMINICANA.search(texto) or "SeNaSa" in f"{titulo} {resumen}":
        texto = re.sub(r"\bsenasa\b", " ", texto)
    en_titulo = _norm(_SUFIJO_MEDIO_DIGITAL.sub("", titulo or ""))
    temas = [t for t, pat in _PATTERNS.items() if pat.search(texto)
             or (t == "Salud" and _SALUD_EN_TITULO.search(en_titulo))]
    if _PATTERN_DEPORTES.search(texto):
        temas = [t for t in temas if t not in ("Coyuntura política", "Salud")]
    if "Salud" in temas and es_espectaculos(url):
        temas = [t for t in temas if t != "Salud"]
    if _PATTERN_TIPO_CAMBIO.search(texto):
        temas = [t for t in temas if t != "KYC / AML / Financiero"]
    if _es_norma_tramite(titulo, resumen):
        temas = [t for t in temas if t == "Coyuntura política"]
    return temas


# "salud" a secas solo en el TITULO: en el resumen suele ser una enumeracion
# ("educación, salud y agua").
_SALUD_EN_TITULO = re.compile(r"\bsalud\b(?! (?:financiera|economica|fiscal|"
                              r"democratica|de la democracia|de la economia))")
# Sufijo de medio de Google News con "Digital" en el nombre ("... - Maraco
# Digital", "- Hoy Digital"): el nombre del diario no dice nada del tema.
_SUFIJO_MEDIO_DIGITAL = re.compile(r"\s[-–|]\s[^-–|]{0,40}\bdigital\s*$", re.IGNORECASE)
# "Lavado" apellido (Marino Lavado, diputado) marcaba KYC/AML. Se exige
# Nombre + Lavado con mayusculas y que no siga "de activos/dinero/capitales".
_APELLIDO_LAVADO = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+) Lavado\b(?! [dD][eE] [aAdDcC])")
# "siembra incertidumbre/dudas" (politica) marcaba Crop.
_FRASES_NEUTRAS = re.compile(
    r"\bsiembra (?:la |el )?(?:incertidumbre|dudas?|miedo|terror|panico|caos|"
    r"desconfianza|zozobra|polemica|temor|confusion|division)"
    # "Obras/Servicios por Impuestos" es un mecanismo de inversion publica,
    # no tributacion (con el plural "impuestos" entraba como KYC).
    r"|\b(?:obras|servicios) por impuestos\b"
    # "Autorizan transferencia financiera a favor de..." = tramite
    # presupuestal entre entidades publicas (El Peruano, a diario).
    r"|\btransferencias? financieras?\b")
# SeNaSa de Republica Dominicana = Seguro Nacional de Salud, no sanidad
# agraria. La prensa dominicana lo escribe "SeNaSa" (se mira el original).
_SENASA_DOMINICANA = re.compile(r"seguro nacional de salud|dominican")
# Nota diaria del precio del dolar: nombra a Sunat (su tipo de cambio) sin
# ser noticia tributaria ni financiera para los clientes.
_PATTERN_TIPO_CAMBIO = re.compile(
    r"precio del dolar|dolar hoy|dolar sunat|cotizacion del dolar|tipo de cambio hoy")


def _sin_homonimos(titulo: str | None, resumen: str | None) -> str:
    t = _SUFIJO_MEDIO_DIGITAL.sub("", titulo or "")
    return _APELLIDO_LAVADO.sub(r"\1", f"{t} {resumen or ''}")


def _es_norma_tramite(titulo: str | None, resumen: str | None) -> bool:
    """Norma de El Peruano/gob.pe ("ENTIDAD — RESOLUCIÓN ...: Designan ...",
    "D000429-2026-MIDAGRI-DM — Se encarga ...") que es tramite interno.
    Solo filas con el " — " de esos scrapers: una NOTICIA "Designan nuevo
    ministro de Salud" si es tema."""
    if " — " not in (titulo or ""):
        return False
    cola = (titulo or "").split(" — ", 1)[1]
    cola = cola.split(": ", 1)[1] if ": " in cola[:90] else cola
    return any(_PATTERN_NORMA_TRAMITE.match(_norm(x))
               for x in (cola, resumen) if x)


def es_normativa(titulo: str | None, resumen: str | None = None) -> bool:
    """True si el contenido referencia normativa (decreto, ley, resolución,
    reglamento, registro oficial, etc.). Independiente del tema."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return False
    return bool(_PATTERN_NORMATIVA.search(texto))


def todos_los_temas() -> list[str]:
    return list(TEMAS.keys())


# ============================================================
# Deteccion de pais por contenido (funcionarios/instituciones/gentilicio)
# ============================================================
# noticias_fuentes.pais es de la fuente, no del articulo: los medios
# regionales (DPL cubre todo LATAM) necesitan el pais por contenido. Señales
# estables a proposito (gentilicio, presidente, siglas de instituciones), no
# ministros, que pueden renunciar el dia de la noticia.
_SEÑALES_PAIS: dict[str, list[str]] = {
    "PE": [
        "peru", "peruano", "peruana", "peruanos", "peruanas",
        "fujimori", "galarreta",
        "congreso de la republica", "congreso peruano",
        "camara de diputados del peru", "senado de la republica del peru",
        "senado del peru",
        # Sin "PRODUCE" (choca con el verbo) ni "camara de diputados" a
        # secas (la usan muchos paises).
        "MEF", "MTC", "MINSA", "MIDAGRI", "MINCETUR", "MINEDU",
        "RENIEC", "ONPE", "JNE", "SUNAT", "BCRP", "PCM", "essalud", "digemid",
    ],
    "EC": [
        "ecuador", "ecuatoriano", "ecuatoriana", "ecuatorianos", "ecuatorianas",
        "noboa", "maria jose pinto",
        "asamblea nacional",
        "IESS", "SRI", "ARCSA", "MSP", "registro oficial", "senae", "senescyt",
    ],
}
_PATTERNS_PAIS = {p: _compile(kws) for p, kws in _SEÑALES_PAIS.items()}

# Otros paises de LATAM: "MINSA" tambien es el ministerio de Nicaragua. Si
# se nombra otro pais, una sola señal de PE/EC no alcanza.
_OTROS_PAISES = _compile([
    "nicaragua", "paraguay", "bolivia", "colombia", "mexico", "chile",
    "argentina", "venezuela", "brasil", "espana", "panama", "costa rica",
    "uruguay", "cuba", "honduras", "el salvador", "guatemala",
    "republica dominicana",
])

# Señales de otro pais que excluyen siempre: "Asamblea Nacional" tambien es
# de Venezuela, y "chavismo"/"TSJ" solo aparecen en notas venezolanas.
_OTRO_PAIS_FUERTE = _compile(["chavismo", "tsj"])

# Fuentes cuyo pais catalogado no es el del articulo (medios regionales, o
# el mismo feed cargado bajo mas de un pais).
FUENTES_MULTIPAIS: set[str] = {
    "DPL News Ecuador", "DPL News Peru", "DPL Tech Ecuador",
    "Bloomberg en Linea", "Criptonoticias",
    "Asociacion Latinoamericana de Internet", "Ebiz Latam",
    # catalogada EC pero es periodismo agrario global
    "Mundo Agropecuario",
}

# Las busquedas guardadas de Google News traen cualquier pais que use el
# termino, pese al "PE"/"EC" del nombre.
_PREFIJOS_MULTIPAIS = ("Google News PE — ", "Google News EC — ")


def es_fuente_multipais(nombre: str) -> bool:
    """True si `noticias_fuentes.nombre` no es confiable como señal de
    pais - hay que reclasificar por contenido via pais_por_contenido()."""
    return nombre in FUENTES_MULTIPAIS or nombre.startswith(_PREFIJOS_MULTIPAIS)


def pais_por_contenido(titulo: str | None, resumen: str | None,
                        pais_fuente: str) -> str | None:
    """Pais real de la noticia por menciones a funcionarios/instituciones
    estables de cada pais. Empate CON señal -> `pais_fuente`. Sin ninguna
    señal de PE ni de EC -> None (el pais de una fuente multipais es
    arbitrario); los callers excluyen None de ambos paises."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return pais_fuente
    if _OTRO_PAIS_FUERTE.search(texto):
        return None
    puntos = {p: len(pat.findall(texto)) for p, pat in _PATTERNS_PAIS.items()}
    pe, ec = puntos.get("PE", 0), puntos.get("EC", 0)
    # Se nombra otro pais y la señal es una sola sigla ambigua: no alcanza
    # para cambiar de pais. `0 <` deja los casos sin señal a la regla de abajo.
    if _OTROS_PAISES.search(texto) and 0 < max(pe, ec) <= 1:
        return pais_fuente
    if pe == 0 and ec == 0:
        return None
    if pe > ec:
        return "PE"
    if ec > pe:
        return "EC"
    return pais_fuente

