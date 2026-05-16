"""Taxonomía y clasificador de proyectos de ley de Ecuador.

Reusa el módulo `scraper.categorias` de Perú (mismas 30 categorías y mismo
algoritmo de scoring por keywords con boundary inicial) pero superpone
keywords adicionales del léxico legislativo ecuatoriano:

  - IESS (vs ESSALUD en Perú)
  - MSP / Ministerio de Salud Pública (vs MINSA en Perú)
  - ARCSA (vs DIGEMID en Perú)
  - SENESCYT, CES, MINEDUC (vs SUNEDU, MINEDU en Perú)
  - Códigos orgánicos: COIP, COFJ, LOSEP, LOES, COGEP, COMYPES, COESCC
  - Registro Oficial (vs Diario Oficial El Peruano)

Mantiene la lógica de override Tecnología/Farma y PRIORIDAD.
"""
from __future__ import annotations

import re

# Import infra del módulo Perú
from scraper.categorias import (
    PRIORIDAD,
    OVERRIDE_DESDE,
    TECH_MIN_KEYWORDS,
    CATEGORIAS as _CATEGORIAS_PE,
    _normalize,
    _build_pattern,
)

# Keywords adicionales por categoría, específicas del contexto ecuatoriano.
# Se MERGEAN con las de Perú (no las reemplazan) para mantener compatibilidad
# con el léxico legislativo general en español.
EXTRA_EC: dict[str, list[str]] = {
    "Educación": [
        "mineduc", "ministerio de educacion", "senescyt", "ces ",
        "ceaaces", "loes", "ley organica de educacion superior",
        "lopei", "lomei", "bachillerato general unificado", "bgu",
    ],
    "Trabajo": [
        "mdt", "ministerio del trabajo", "codigo del trabajo",
        "trabajadores ecuatorianos", "iess afiliacion", "afiliados al iess",
        "decimo tercero", "decimo cuarto", "fondo de reserva",
        "mandato constituyente 8", "mandato 8",
    ],
    "Salud": [
        "iess", "msp", "ministerio de salud publica",
        "establecimientos de salud", "ciess", "hospital basico",
        "centro de salud tipo", "isspol", "isspol salud",
        "modelo de atencion integral",
    ],
    "Farma": [
        "arcsa", "agencia de regulacion y control sanitario",
        "cnmb", "cuadro nacional de medicamentos basicos",
        "registro sanitario nacional",
    ],
    "Pensiones": [
        "iess jubilacion", "issfa", "isspol", "fondo de cesantia",
        "fondo de reserva", "biess",
    ],
    "Tributos": [
        "sri", "servicio de rentas internas",
        "ley de regimen tributario interno", "lrti",
        "iva ecuatoriano", "rise", "rimpe",
        "anticipo del impuesto a la renta",
    ],
    "Banca": [
        "superintendencia de bancos", "junta de politica monetaria",
        "bce ", "banco central del ecuador",
        "codigo monetario y financiero", "comf",
    ],
    "Energía": [
        "arconel", "celec", "cenace", "petroecuador",
        "ley organica del sector electrico", "loserse",
        "subsidios energeticos",
    ],
    "Minería": [
        "arcom", "agencia de regulacion y control minero",
        "ley de mineria del ecuador", "regalia minera",
    ],
    "Pesca": [
        "subsecretaria de recursos pesqueros", "instituto nacional de pesca",
        "inp pesca",
    ],
    "Agricultura": [
        "magap", "mag ", "ministerio de agricultura y ganaderia",
        "agrocalidad", "iniap",
    ],
    "Ambiente": [
        "maate", "ministerio del ambiente",
        "registro forestal", "ley organica de recursos hidricos",
        "lorh", "sistema nacional de areas protegidas", "snap",
    ],
    "Telecomunicaciones": [
        "arcotel", "agencia de regulacion y control de las telecomunicaciones",
        "ley organica de telecomunicaciones", "lot",
        "espectro radioelectrico",
    ],
    "Transporte": [
        "ant ", "agencia nacional de transito",
        "comision de transito del ecuador", "cte",
        "ley organica de transporte terrestre", "lottts",
    ],
    "Consumo masivo": [
        "ley organica de defensa del consumidor",
        "lodc", "superintendencia de control del poder de mercado",
        "scpm",
    ],
    "Control de la actividad privada": [
        "superintendencia de companias", "supercia",
        "supercom", "scpm",
        "ley de companias", "registro mercantil",
    ],
    "Tecnología": [
        "ley organica de proteccion de datos personales",
        "lopdp ecuador", "agencia de regulacion y control de proteccion de datos",
        "lopdp", "estrategia ecuador digital",
    ],
    "Mype": [
        "comypes", "ley organica de economia popular y solidaria",
        "loeps", "seps", "superintendencia de economia popular",
        "fondo de garantia mype",
    ],
    "Saneamiento": [
        "senagua", "agencia de regulacion y control del agua",
        "arca", "empresa publica de agua",
    ],
    "Construcción": [
        "miduvi", "ministerio de desarrollo urbano y vivienda",
    ],
    "Infraestructura": [
        "mtop", "ministerio de transporte y obras publicas",
    ],
    "Otros": [
        # Códigos transversales mencionados frecuentemente sin tema específico
        # claro: caen acá si no hay otro match más fuerte.
        "coip", "codigo organico integral penal",
        "cofj", "codigo organico de la funcion judicial",
        "losep", "ley organica del servicio publico",
        "cogep", "codigo organico general de procesos",
        "registro oficial",
    ],
}

# Merge: para cada categoría, append los extras al final.
CATEGORIAS: dict[str, list[str]] = {
    cat: list(kws) + EXTRA_EC.get(cat, []) for cat, kws in _CATEGORIAS_PE.items()
}

# Recompila los patrones con keywords merged
_KW_RE: dict[str, list[re.Pattern]] = {
    cat: [_build_pattern(kw) for kw in kws] for cat, kws in CATEGORIAS.items()
}


def classify(titulo: str | None, sumilla: str | None = None) -> str:
    """Devuelve UN tema (string). Si nada matchea, 'Otros'."""
    text = _normalize(f"{titulo or ''} {sumilla or ''}")
    scores: dict[str, int] = {}
    for cat, patterns in _KW_RE.items():
        s = sum(1 for p in patterns if p.search(text))
        if s:
            scores[cat] = s
    if not scores:
        return "Otros"
    max_s = max(scores.values())
    best = [c for c, v in scores.items() if v == max_s]
    if len(best) == 1:
        return best[0]
    for cat in PRIORIDAD:
        if cat in best:
            return cat
    return best[0]


def count_matches(titulo: str | None, sumilla: str | None, categoria: str) -> int:
    patterns = _KW_RE.get(categoria)
    if not patterns:
        return 0
    text = _normalize(f"{titulo or ''} {sumilla or ''}")
    return sum(1 for p in patterns if p.search(text))


def all_categorias() -> list[str]:
    return list(CATEGORIAS.keys()) + ["Otros"]


# Exporta también las constantes del módulo Perú para que sean importables
# desde este módulo (PRIORIDAD, OVERRIDE_DESDE, TECH_MIN_KEYWORDS).
__all__ = [
    "CATEGORIAS",
    "PRIORIDAD",
    "OVERRIDE_DESDE",
    "TECH_MIN_KEYWORDS",
    "classify",
    "count_matches",
    "all_categorias",
]
