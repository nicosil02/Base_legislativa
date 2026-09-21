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
        # "Rogers Valencia" (ministro MINCETUR) se saco 2026-09-21 - mismo
        # criterio que "ANA"/"premier"/"fiscal" mas abajo: verificado
        # contra produccion (30 dias), 8 de 8 menciones eran turismo/
        # comercio exterior sin ninguna señal digital real (ferias de
        # turismo, vuelos, terminal portuario, Machu Picchu) - el nombre
        # del ministro no es proxy de que la nota sea sobre digital, es
        # proxy de "MINCETUR publico algo", que es casi cualquier cosa.
        # "Álvarez Miranda" (Justicia, dueño de ANPD) se deja por ahora -
        # mismo riesgo estructural pero sin evidencia real todavia (0
        # menciones en 30 dias) - revisar si empieza a aparecer.
        "Álvarez Miranda", "Alvarez Miranda",
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

# Bug real 2026-09-21 (Nicolas, primero en las alertas de WhatsApp - "0
# relevantes" - y confirmado despues tambien en las paginas Noticias
# PE/EC via auditoria en vivo contra produccion, 2026-09-21 mas tarde el
# mismo dia): "presidente"/"presidenta" (palabras de Coyuntura política)
# matchea IGUAL al presidente de un club de futbol que al de la
# Republica. El primer intento de arreglar esto solo aplicaba el veto
# dentro del digest de WhatsApp (noticias/digest.py) razonando que
# clasificar() "tambien lo usan las paginas Noticias PE/EC" como motivo
# para NO tocarlo - exactamente al reves: como TODOS los consumidores
# (WhatsApp y las paginas) comparten clasificar(), el veto tiene que
# vivir aca para que todos lo hereden. Verificado en vivo: Miguel
# Montalvo (presidente de Barcelona SC) y Jose David Jimenez (presidente
# de Emelec) seguian apareciendo como "Coyuntura política" en la pagina
# Noticias EC pese al fix del digest.
KEYWORDS_DEPORTES = [
    "liga ecuabet", "liga pro", "copa sudamericana", "copa libertadores",
    "cuadrangular", "hexagonal", "hinchas", "hinchada", "estadio",
    "futbolista", "futbolistas", "delantero", "defensor", "arquero",
    "director tecnico", "director técnico", "barcelona sc", "emelec",
]
_PATTERN_DEPORTES = _compile(KEYWORDS_DEPORTES)


def es_deportivo(titulo: str | None, resumen: str | None = None) -> bool:
    """True si el contenido es sobre futbol/deportes - independiente de
    que tema le haya asignado clasificar() (un "presidente de club" cuela
    como Coyuntura política sin esto)."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return False
    return bool(_PATTERN_DEPORTES.search(texto))


def clasificar(titulo: str | None, resumen: str | None = None) -> list[str]:
    """Lista de temas detectados en el contenido. Orden estable."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return []
    temas = [t for t, pat in _PATTERNS.items() if pat.search(texto)]
    if "Coyuntura política" in temas and _PATTERN_DEPORTES.search(texto):
        temas = [t for t in temas if t != "Coyuntura política"]
    return temas


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
                        pais_fuente: str) -> str | None:
    """Pais real de la noticia por menciones a funcionarios/instituciones
    estables de cada pais. Empate CON señal (ambos paises mencionados por
    igual) -> se queda con `pais_fuente`. Devuelve None si no hay NINGUNA
    señal de PE ni de EC - bug real 2026-09-21 (Nicolas: "las noticias...
    no son de Peru... son 0 relevantes"): una nota de Argentina (Javier
    Milei, economia, elecciones 2027) via "Bloomberg en Linea" (fuente
    multi-pais, catalogada PE) no menciona nada de Peru NI de Ecuador -
    quedarse con pais_fuente en ese caso asume que toda nota sin señal
    conocida es del pais registrado de la fuente, que para una fuente
    multi-pais es un dato arbitrario, no una inferencia real. El caller
    (`_noticias_desde`) ya excluye None de ambos paises."""
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
    if pe == 0 and ec == 0:
        return None
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
    # Sin NINGUNA señal de PE ni EC -> None (no asumir el pais de la
    # fuente, es arbitrario para una fuente multi-pais) - bug real
    # 2026-09-21, verificado en produccion: nota 100% de Argentina
    # (Javier Milei) via "Bloomberg en Linea" (catalogada PE) se mandaba
    # como si fuera noticia peruana.
    assert pais_por_contenido(
        "Cómo llegaría la economía de Milei a las elecciones de 2027, según analistas",
        None, "PE") is None
    assert pais_por_contenido("El chavismo y la oposición continúan el diálogo",
                               None, "EC") is None
    assert pais_por_contenido(None, None, "PE") == "PE", \
        "texto vacio (titulo/resumen None) es un caso distinto - no hay nada que analizar, se queda con pais_fuente"
    # Falsos positivos reales 2026-09-20 (verificados contra 30 dias de
    # produccion, fuentes multi-pais tipo Criptonoticias/DPL que cubren
    # TODO LATAM, no solo Peru/Ecuador):
    assert pais_por_contenido(
        "Solana gana velocidad gracias a su nueva actualización",
        "La activación de SIMD-0525 redujo a 250 ms el tiempo de slot, el "
        "intervalo en que Solana produce nuevos bloques.", "EC") is None, \
        '"produce" (verbo) no debe matchear el Ministerio de la Produccion (PE), y sin otra señal es None'
    assert pais_por_contenido(
        "Nicaragua fortalece su preparación para la IA en salud",
        "el Ministerio de Salud de Nicaragua (MINSA) y la OPS...", "EC") == "EC", \
        "MINSA tambien es de Nicaragua - una sola sigla ambigua no alcanza si se nombra otro pais"
    assert pais_por_contenido(
        "Desmantelan 2 granjas clandestinas de minería de Bitcoin en Paraguay",
        "La Cámara de Diputados solicitó a la ANDE informes...", "EC") == "EC", \
        '"camara de diputados" a secas es generico en LATAM, no exclusivo de Peru'
    print("OK temas: pais_por_contenido detecta por funcionarios/instituciones estables")


def _test_ministro_no_es_proxy_de_tema():
    """Bug real 2026-09-21 (auditoria en vivo pedida por Nicolas: "quiero
    que aprendas mejor... las noticias que realmente nos interesan"):
    "Rogers Valencia" (ministro MINCETUR) estaba en Tech/Digital - 8 de 8
    menciones reales en 30 dias eran turismo/comercio exterior sin
    ninguna señal digital. El nombre de un ministro NO es proxy de que la
    nota sea del tema por el que se agrego - es proxy de "su ministerio
    publico algo", que cubre todo lo que hace ese ministerio."""
    assert "Tech / Digital" not in clasificar(
        "Ministro Rogers Valencia visita terminal multipropósito de "
        "DP World en el Callao")
    assert clasificar(
        "Mincetur destaca nueva conexión aérea directa entre São Paulo y "
        "Cusco como impulso histórico para el turismo") == []
    print("OK temas: un ministro de turismo/comercio no marca Tech/Digital "
          "solo por su nombre")


def _test_es_deportivo():
    # Casos reales 2026-09-21 (verificados en produccion, 2 veces: primero
    # en las alertas de WhatsApp, despues via auditoria en vivo se
    # confirmo que TAMBIEN seguian apareciendo en las paginas Noticias
    # PE/EC, porque el primer intento solo veteaba dentro del digest y no
    # en clasificar() mismo) - presidentes de club NO deben clasificar
    # como Coyuntura política en ningun consumidor.
    assert clasificar("Miguel Montalvo, presidente de Barcelona SC, y el "
                       "cambio del club a sociedad anónima", None) == []
    assert es_deportivo("Miguel Montalvo, presidente de Barcelona SC, y el "
                         "cambio del club a sociedad anónima", None)
    assert es_deportivo(
        "José David Jiménez, presidente de Emelec, plantea revisar el "
        "formato de Liga Ecuabet para recuperar a los hinchas en los estadios")
    # Un presidente real de pais NO debe marcarse como deportivo, y SI
    # debe seguir clasificando como Coyuntura política.
    assert not es_deportivo("Presidenta Keiko Fujimori lidera sesión de "
                             "Consejo de Ministros en Palacio de Gobierno")
    assert clasificar("Presidenta Keiko Fujimori lidera sesión de "
                       "Consejo de Ministros en Palacio de Gobierno") == ["Coyuntura política"]
    print("OK temas: clasificar() ya no marca presidentes de club (Barcelona SC, "
          "Emelec) como Coyuntura política, pero si a presidentes reales")


if __name__ == "__main__":
    _demo()
    _test_ministro_no_es_proxy_de_tema()
    _test_es_deportivo()
