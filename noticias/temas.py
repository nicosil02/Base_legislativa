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
        "presidente", "presidenta", "congreso", "ministro", "ministra",
        "gobierno", "gabinete", "premier", "vicepresidente",
        "vicepresidenta", "vacancia", "interpelacion", "interpelación",
        "moción de censura", "moción", "denuncia constitucional",
        "fiscalía", "fiscalia", "fiscal", "ejecutivo", "legislativo",
        "asamblea nacional", "diputado", "diputada", "senador",
        "senadora", "oposición", "oposicion", "oficialismo",
        "elecciones", "comicios", "JNE", "ONPE", "RENIEC", "CNE",
        "candidato", "candidata", "partido político", "partido politico",
        "campaña electoral", "Boluarte", "Noboa", "PCM",
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
    ],
    "Crop": [
        "agricultura", "agrícola", "agricola", "agropecuario",
        "agropecuaria", "ganaderia", "ganadería", "semilla",
        "semillas", "riego", "siembra", "cosecha", "agroexport",
        "agroexportación", "agroexportacion", "MIDAGRI", "SENASA",
        "AGROCALIDAD", "ANA", "agrario", "conveagro", "CONVEAGRO",
        "AGAP", "CEPES", "agraria.pe", "transgénicos", "transgenicos",
        "OGM", "fertilizantes", "campesino", "campesina", "agro",
        "INIAP", "MAG", "MAGAP", "produccion agropecuaria",
        "producción agropecuaria",
    ],
    "KYC / AML / Financiero": [
        "lavado de activos", "prevención de lavado",
        "prevencion de lavado", "antilavado", "anti-lavado",
        "financiamiento del terrorismo", "PEP", "UIF",
        "SBS", "UAF", "due diligence", "GAFI", "GAFILAT",
        "FinCEN", "compliance financiero", "compliance",
        "AFP", "ONP", "SUNAT", "SRI",
        "tributo", "tributos", "impuesto", "fiscal",
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
