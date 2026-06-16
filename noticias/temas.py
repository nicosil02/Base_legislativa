"""Clasificacion tematica de noticias por keywords en titulo+resumen.

Una noticia puede tener varios temas. La fuente da una pista (categoria),
pero el contenido manda: Gestion (Coyuntura) puede publicar de tech, y
Niubox (Tech) puede publicar de coyuntura electoral.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# Cada tema mapea a una lista de keywords/regex.
# - Strings simples: match palabra completa (\b...\b) case-insensitive
# - Strings con espacios: match frase exacta
# Todo se normaliza sin tildes antes de comparar para tolerar variaciones.
TEMAS: dict[str, list[str]] = {
    "Coyuntura política": [
        "presidente", "congreso", "ministro", "ministra", "gobierno",
        "gabinete", "premier", "vicepresidente", "vicepresidenta",
        "vacancia", "interpelacion", "moción de censura", "moción",
        "denuncia constitucional", "fiscalía", "fiscalia", "fiscal",
        "ejecutivo", "legislativo", "asamblea", "diputado", "diputada",
        "senador", "senadora", "oposición", "oposicion", "oficialismo",
        "elecciones", "comicios", "JNE", "ONPE", "RENIEC", "CNE",
        "candidato", "candidata", "partido político", "partido politico",
        "campaña electoral",
    ],
    "Salud": [
        "hospital", "paciente", "enfermedad", "epidemia", "brote",
        "MINSA", "MSP", "ESSALUD", "IESS", "SIS", "SOLCA",
        "atencion medica", "atención médica", "atencion primaria",
        "cobertura sanitaria", "sistema de salud", "emergencia sanitaria",
        "cancer", "cáncer", "diabetes", "tuberculosis", "dengue",
        "covid", "salud mental",
    ],
    "Farma / Medicamentos": [
        "medicamento", "medicamentos", "vacuna", "vacunación",
        "vacunacion", "antibiotico", "antibiótico", "laboratorio",
        "farmaceutica", "farmacéutica", "industria farma",
        "ARCSA", "DIGEMID", "ANVISA", "FDA", "EMA", "OMS",
        "biosimilar", "biotecnología", "biotecnologia",
        "ensayo clinico", "ensayo clínico", "patente farmacéutica",
        "registro sanitario", "DCI", "principio activo",
        "esperantra", "lazo rosado", "alafar",
    ],
    "Tech / Digital": [
        "digital", "tecnología", "tecnologia", "ciberseguridad",
        "datos personales", "proteccion de datos", "protección de datos",
        "inteligencia artificial", "IA", "AI", "fintech", "criptomoneda",
        "criptomonedas", "cripto", "bitcoin", "blockchain",
        "telecomunicaciones", "OSIPTEL", "ARCOTEL",
        "5G", "internet", "ciberataque", "hackeo", "phishing",
        "fraude digital", "ecommerce", "comercio electrónico",
        "comercio electronico", "neutralidad de red", "PCM digital",
        "transformación digital", "transformacion digital",
        "INDECOPI", "Niubox", "Hiperderecho", "ALAI",
    ],
    "Agrario / Agropecuario": [
        "agricultura", "agrícola", "agricola", "agropecuario",
        "agropecuaria", "ganaderia", "ganadería", "semilla",
        "semillas", "riego", "siembra", "cosecha", "agroexport",
        "agroexportación", "agroexportacion", "MIDAGRI", "SENASA",
        "AGROCALIDAD", "ANA", "agrario", "conveagro", "AGAP",
        "CEPES", "agraria.pe", "transgénicos", "transgenicos",
        "OGM", "fertilizantes", "campesino", "campesina",
    ],
    "KYC / AML / Financiero": [
        "lavado de activos", "prevención de lavado",
        "prevencion de lavado", "antilavado", "anti-lavado",
        "financiamiento del terrorismo", "PEP", "UIF",
        "SBS", "UAF", "due diligence", "GAFI", "GAFILAT",
        "FinCEN", "AFI", "compliance financiero",
        "AFP", "ONP", "SUNAT", "SRI", "tributo", "tributos",
        "impuesto", "fiscal", "evasión fiscal", "evasion fiscal",
        "regimen tributario",
    ],
    "Laboral / Pensiones": [
        "afp", "onp", "pension", "pensión", "jubilacion", "jubilación",
        "sindicato", "huelga", "trabajadores",
        "salario", "sueldo minimo", "sueldo mínimo",
        "RMV", "MTPE", "ministerio de trabajo",
        "remuneracion", "remuneración", "cts",
    ],
    "Regulatorio / Normativa": [
        "decreto", "decreto supremo", "decreto urgencia",
        "decreto legislativo", "resolución ministerial",
        "resolucion ministerial", "ley", "proyecto de ley",
        "norma", "normativa", "reglamento", "consulta publica",
        "consulta pública", "publicado en el peruano",
        "registro oficial", "diario oficial",
    ],
}


def _norm(s: str) -> str:
    """Lowercase + sin tildes + colapsa espacios."""
    if not s:
        return ""
    s = s.lower()
    # Quitar tildes
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", s)


# Pre-compilamos: por cada tema, un regex grande con alternativas
def _compile_tema_patterns() -> dict[str, re.Pattern]:
    out = {}
    for tema, kws in TEMAS.items():
        alts = []
        for kw in kws:
            n = _norm(kw)
            if " " in n:
                # frase
                alts.append(re.escape(n))
            else:
                # palabra completa
                alts.append(rf"\b{re.escape(n)}\b")
        if alts:
            out[tema] = re.compile("|".join(alts), re.IGNORECASE)
    return out


_PATTERNS = _compile_tema_patterns()


def clasificar(titulo: str | None, resumen: str | None = None) -> list[str]:
    """Devuelve lista de temas detectados en el contenido. Orden estable."""
    texto = _norm(f"{titulo or ''} {resumen or ''}")
    if not texto.strip():
        return []
    hits = []
    for tema, pat in _PATTERNS.items():
        if pat.search(texto):
            hits.append(tema)
    return hits


def todos_los_temas() -> list[str]:
    """Lista ordenada de temas soportados."""
    return list(TEMAS.keys())
