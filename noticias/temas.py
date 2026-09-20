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


# ============================================================
# Deteccion de pais por contenido (funcionarios/instituciones/gentilicio)
# ============================================================
#
# Bug real 2026-09-20: Nicolas reporto que una noticia 100% peruana (la
# renuncia de Rafael Rey como Ministro de Transportes) nunca le llego -
# la agarro "DPL News Ecuador" (dplnews.com, cubre TODO LATAM, no solo
# Ecuador) y quedo archivada bajo pais="EC" porque noticias_fuentes.pais
# es un dato de LA FUENTE, no del articulo. Peor: DPL esta cargado 3
# veces en el catalogo (DPL News Peru->PE, DPL News Ecuador->EC, DPL Tech
# Ecuador->EC), las 3 apuntando al MISMO feed (dplnews.com/feed/) - como
# noticias.url es UNIQUE, cada articulo se lo queda la primera de las 3
# filas que lo sincronice primero, asi que el pais que le toca es
# esencialmente al azar, no por contenido real.
#
# Estas listas son señales ESTABLES a proposito (gentilicio + nombre del
# presidente actual + siglas de instituciones que no cambian de nombre
# cada reorganizacion de gabinete) en vez de listar ministros - un
# ministro puede renunciar el mismo dia que sale la noticia (literalmente
# el caso que motivo esto).
_SEÑALES_PAIS: dict[str, list[str]] = {
    "PE": [
        "peru", "peruano", "peruana", "peruanos", "peruanas",
        "fujimori", "galarreta",
        "congreso de la republica", "congreso peruano",
        "camara de diputados del peru", "senado de la republica del peru",
        "senado del peru",
        # ponytail (2026-09-20): "PRODUCE" (Ministerio de la Produccion) se
        # saco - choca con el verbo comun "produce" (ej. "Solana produce
        # nuevos bloques", nota de cripto sin nada que ver con Peru,
        # verificado en vivo). "camara de diputados"/"senado de la
        # republica" a secas tambien se sacaron - son nombres genericos
        # que usan MUCHOS paises de LATAM (Paraguay, Argentina, Chile...),
        # no exclusivos de Peru; solo cuentan calificados con "del peru".
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

# Veto: nombres de OTROS paises de LATAM que las fuentes multi-pais
# (Criptonoticias, DPL) tambien cubren. Bug real 2026-09-20: "MINSA"
# tambien es el nombre del Ministerio de Salud de NICARAGUA, y "Camara de
# Diputados" es generico - sin este veto, una nota 100% sobre Nicaragua o
# Paraguay que de pasada nombra su propio ministerio/camara se colaba
# como si fuera de Peru. Si el texto nombra a otro pais y NO nombra a
# Peru/Ecuador por su nombre, no hay señal confiable - se descarta el
# puntaje de PE/EC entero y se usa `pais_fuente` (fallback de siempre).
_OTROS_PAISES = _compile([
    "nicaragua", "paraguay", "bolivia", "colombia", "mexico", "chile",
    "argentina", "venezuela", "brasil", "espana", "panama", "costa rica",
    "uruguay", "cuba", "honduras", "el salvador", "guatemala",
    "republica dominicana",
])

# Fuentes cuyo `noticias_fuentes.pais` catalogado NO es confiable como
# pais del articulo - medios/feeds regionales LATAM, verificados en vivo
# 2026-09-20 (dominio no especifico a un pais, o el mismo feed cargado
# bajo mas de un pais en el catalogo).
FUENTES_MULTIPAIS: set[str] = {
    "DPL News Ecuador", "DPL News Peru", "DPL Tech Ecuador",
    "Bloomberg en Linea", "Criptonoticias",
    "Asociacion Latinoamericana de Internet", "Ebiz Latam",
}


def pais_por_contenido(titulo: str | None, resumen: str | None,
                        pais_fuente: str) -> str:
    """Pais real de la noticia por menciones a funcionarios/instituciones
    estables de cada pais. Empate (incluido 0-0, el caso comun de una nota
    que no menciona ningun funcionario) -> se queda con `pais_fuente` sin
    cambios, es el comportamiento de siempre."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return pais_fuente
    puntos = {p: len(pat.findall(texto)) for p, pat in _PATTERNS_PAIS.items()}
    pe, ec = puntos.get("PE", 0), puntos.get("EC", 0)
    # Veto: si se nombra a OTRO pais de LATAM y la señal ganadora es una
    # sola sigla ambigua (ej. "MINSA" tambien es de Nicaragua), no alcanza -
    # se necesitan 2+ señales, o ninguna mencion de otro pais, para confiar.
    if _OTROS_PAISES.search(texto) and max(pe, ec) <= 1:
        return pais_fuente
    if pe > ec:
        return "PE"
    if ec > pe:
        return "EC"
    return pais_fuente


def _demo():
    # Caso real 2026-09-20 que motivo esto: DPL News Ecuador (catalogada
    # pais='EC') traia esta noticia 100% peruana.
    assert pais_por_contenido(
        "Rafael Rey deja el Ministerio de Transportes y Comunicaciones de Perú",
        None, "EC") == "PE"
    assert pais_por_contenido(
        "Noboa llega a Estados Unidos para participar en la Asamblea General de la ONU",
        None, "PE") == "EC"
    # Sin señales de ningun pais -> se queda con lo que ya tenia la fuente.
    assert pais_por_contenido("El chavismo y la oposición continúan el diálogo",
                               None, "EC") == "EC"
    assert pais_por_contenido(None, None, "PE") == "PE"
    # Falsos positivos reales 2026-09-20 (verificados contra 30 dias de
    # produccion, fuentes multi-pais tipo Criptonoticias/DPL que cubren
    # TODO LATAM, no solo Peru/Ecuador):
    assert pais_por_contenido(
        "Solana gana velocidad gracias a su nueva actualización",
        "La activación de SIMD-0525 redujo a 250 ms el tiempo de slot, el "
        "intervalo en que Solana produce nuevos bloques.", "EC") == "EC", \
        '"produce" (verbo) no debe matchear el Ministerio de la Produccion (PE)'
    assert pais_por_contenido(
        "Nicaragua fortalece su preparación para la IA en salud",
        "el Ministerio de Salud de Nicaragua (MINSA) y la OPS...", "EC") == "EC", \
        "MINSA tambien es de Nicaragua - una sola sigla ambigua no alcanza si se nombra otro pais"
    assert pais_por_contenido(
        "Desmantelan 2 granjas clandestinas de minería de Bitcoin en Paraguay",
        "La Cámara de Diputados solicitó a la ANDE informes...", "EC") == "EC", \
        '"camara de diputados" a secas es generico en LATAM, no exclusivo de Peru'
    print("OK temas: pais_por_contenido detecta por funcionarios/instituciones estables")


if __name__ == "__main__":
    _demo()
