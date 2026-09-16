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
import unicodedata


TEMAS: dict[str, list[str]] = {
    "Coyuntura política": [
        # Instituciones y roles del poder (relevantes cuando el foco es
        # política; asumimos que el usuario prefiere cobertura amplia).
        "presidente", "presidenta", "vicepresidente", "vicepresidenta",
        # ponytail (2026-09-14): "premier" solo (sin "peruano"/nombre) se
        # sacó - matcheaba "Premier League" en cualquier nota deportiva
        # (Manchester City, Chelsea, Liverpool...), coyuntura de futbol
        # ingles pasando como coyuntura politica. El cargo ya se detecta
        # via "gabinete"/"consejo de ministros"/el apellido del premier
        # (ver "Galarreta" mas abajo).
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
        # ponytail (2026-09-14): "Keiko" sola (sin "Fujimori") se saco -
        # matcheaba notas de entretenimiento sobre la orca de "Free Willy"
        # (documental Netflix). "Fujimori" solo ya cubre la cobertura
        # politica real sin ese choque.
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
    ],
    "Tech / Digital": [
        "digital", "tecnología", "tecnologia", "ciberseguridad",
        "datos personales", "proteccion de datos", "protección de datos",
        "inteligencia artificial", "fintech", "criptomoneda",
        "criptomonedas", "cripto", "bitcoin", "blockchain",
        "telecomunicaciones", "OSIPTEL", "ARCOTEL", "SPDP",
        "5G", "internet", "ciberataque", "hackeo", "phishing",
        "fraude digital", "ecommerce", "comercio electrónico",
        "comercio electronico", "neutralidad de red",
        "transformación digital", "transformacion digital",
        "INDECOPI", "Niubox", "Hiperderecho", "ALAI",
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
        # Ministro de Justicia y de Comercio Exterior actuales
        # (gabinete Galarreta) — políticamente relevantes para digital.
        "Álvarez Miranda", "Alvarez Miranda",   # Justicia → dueño de ANPD
        "Rogers Valencia",                       # MINCETUR
    ],
    "Crop": [
        "agricultura", "agrícola", "agricola", "agropecuario",
        "agropecuaria", "ganaderia", "ganadería", "semilla",
        "semillas", "riego", "siembra", "cosecha", "agroexport",
        "agroexportación", "agroexportacion", "MIDAGRI", "SENASA",
        # ponytail (2026-09-15): "ANA" (Autoridad Nacional del Agua) sola
        # se saco - matcheaba el nombre propio "Ana" (comun en español)
        # en cualquier texto que mencionara a alguien con ese nombre,
        # verificado en vivo con el resumen real de una sesion de la
        # Comision de Salud que citaba a la diputada "Ana Luisa Yufra
        # Lugo" y quedaba mal clasificada como "Crop". Mismo criterio que
        # "premier"/"Keiko" mas abajo.
        "AGROCALIDAD", "agrario", "conveagro", "CONVEAGRO",
        "AGAP", "CEPES", "agraria.pe", "transgénicos", "transgenicos",
        "OGM", "fertilizantes", "campesino", "campesina", "agro",
        "INIAP", "MAG", "MAGAP", "produccion agropecuaria",
        "producción agropecuaria",
        # Agroquimicos - bug real 2026-09-16 (Nicolas: "tema prioritario
        # hoy es lo del TC respecto a plaguicidas"): la categoria Crop no
        # tenia NINGUNA palabra de plaguicidas/pesticidas, el corazon del
        # negocio de proteccion de cultivos de Bayer/Syngenta - se
        # confirmo que un titulo real sobre "control de pesticidas" no
        # clasificaba en nada.
        "plaguicida", "plaguicidas", "pesticida", "pesticidas",
        "agroquímico", "agroquimico", "agroquímicos", "agroquimicos",
        "glifosato", "herbicida", "herbicidas", "insecticida", "insecticidas",
        "fungicida", "fungicidas",
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
        "tributo", "tributos", "impuesto",
        # ponytail (2026-09-15): "fiscal" sola se saco - es ambigua en
        # español ("fiscal" = tributario, pero tambien = del Ministerio
        # Publico/Fiscalia, sentido totalmente distinto), verificado en
        # vivo con una "carpeta fiscal" (denuncias, sentido judicial) que
        # quedaba mal clasificada como KYC/AML/Financiero. Las frases
        # compuestas de abajo ya cubren el sentido tributario sin
        # ambiguedad.
        "evasión fiscal", "evasion fiscal", "régimen tributario",
        "regimen tributario",
        "superintendencia de banca", "banca y seguros",
        "lavado", "activos ilícitos", "activos ilicitos",
    ],
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


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", s)


def _compile(kws: list[str]) -> re.Pattern:
    alts = []
    for kw in kws:
        n = _norm(kw)
        if " " in n:
            alts.append(re.escape(n))
        else:
            alts.append(rf"\b{re.escape(n)}\b")
    return re.compile("|".join(alts), re.IGNORECASE)


_PATTERNS = {tema: _compile(kws) for tema, kws in TEMAS.items()}
_PATTERN_NORMATIVA = _compile(KEYWORDS_NORMATIVA)


def clasificar(titulo: str | None, resumen: str | None = None) -> list[str]:
    """Lista de temas detectados en el contenido. Orden estable."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return []
    return [t for t, pat in _PATTERNS.items() if pat.search(texto)]


def es_normativa(titulo: str | None, resumen: str | None = None) -> bool:
    """True si el contenido referencia normativa (decreto, ley, resolución,
    reglamento, registro oficial, etc.). Independiente del tema."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return False
    return bool(_PATTERN_NORMATIVA.search(texto))


def todos_los_temas() -> list[str]:
    return list(TEMAS.keys())
