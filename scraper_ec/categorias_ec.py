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
        # Términos descubiertos sampleando "Otros" en la data real
        "secap", "capacitacion profesional", "licencia por calamidad",
        "licencia de maternidad", "licencia de paternidad",
        "licencia por embarazo", "lactancia, maternidad",
        "regimen del servicio publico", "servidores publicos",
        "estabilidad laboral", "salario digno", "salario basico",
        "afiliacion al seguro social",
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
        # Patterns ecuatorianos descubiertos: naturaleza/biodiversidad
        "biodiversidad", "biodiversid",
        "derechos de la naturaleza", "naturaleza frente",
        "actividades extractivistas", "actividades extractivas",
        "extractivismo", "extractivism",
        "recursos naturales", "recursos hidricos",
        "ecosistema", "ecosistem",
        "patrimonio natural", "areas protegidas",
        "cambio climatico", "deforestacion",
        "fauna silvestre", "vida silvestre",
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
        "aeronaves no tripuladas", "vehiculos no tripulados",
        "dron ", "drones",
    ],
    "Inmobiliario": [
        # Patterns ecuatorianos descubiertos en "Otros"
        "propiedad horizontal", "ley de propiedad horizontal",
        "inquilinato", "arrendamiento de", "arrendatario",
        "ley de inquilinato", "registro de la propiedad",
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
        "economia popular y solidaria",
        "emprendimiento", "emprendedor", "emprendimi",
        "asociatividad", "microempresa",
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
        # Códigos transversales sin tema específico claro
        "losep", "ley organica del servicio publico",
        "registro oficial",
    ],
}


# Keywords del clasificador de Perú que NO aplican bien en Ecuador y dan
# falsos positivos. Se REMUEVEN antes de mergear con los extras EC.
# Ejemplo: "fiscal" en Tributos (PE) matchea "Fiscal General" en EC, que
# es la autoridad penal — no tiene nada que ver con impuestos.
EXCLUDE_PE: dict[str, set[str]] = {
    "Tributos": {
        "fiscal",          # PE: "fiscal" en "fiscalización tributaria". EC: "Fiscal General" (penal). False positive.
    },
}


# Categorías NUEVAS específicas de Ecuador que no existen en Perú.
# Se agregan al diccionario CATEGORIAS y a PRIORIDAD (en posición alta).
EXTRA_CATEGORIAS_EC: dict[str, list[str]] = {
    "Justicia": [
        # Función judicial / órganos del sistema penal
        "fiscal general", "fiscalia general", "fiscalia general del estado",
        "funcion judicial", "consejo de la judicatura",
        "ministerio publico", "defensoria publica",
        "codigo organico integral penal", "coip",
        "codigo organico de la funcion judicial", "cofj",
        "codigo organico general de procesos", "cogep",
        # Crimen organizado y delitos graves
        "crimen organizado", "delincuencia organizada",
        "narcotrafico", "narcotraficante",
        "lavado de activos", "extincion de dominio",
        "trata de personas", "trafico ilicito de migrantes",
        "menoscabo de la integridad",
        # Investigación / cooperación
        "cooperacion eficaz", "investigacion preprocesal",
        "investigacion penal",
        # Violencia y derechos
        "violencia contra la mujer", "violencia obstetrica",
        "violencia intrafamiliar", "feminicidio", "femicidio",
        # Corrupción
        "corrupcion", "anticorrupcion",
        # Otros instrumentos
        "ley notarial", "personas desaparecidas",
        "ley organica de actuacion en casos de personas",
    ],
}

# Merge: para cada categoría PE, REMUEVE keywords excluidos (EXCLUDE_PE) y
# APPEND extras EC (EXTRA_EC). Luego agrega categorías nuevas EC-only.
CATEGORIAS: dict[str, list[str]] = {
    cat: [kw for kw in kws if kw not in EXCLUDE_PE.get(cat, set())] + EXTRA_EC.get(cat, [])
    for cat, kws in _CATEGORIAS_PE.items()
}
CATEGORIAS.update(EXTRA_CATEGORIAS_EC)


# PRIORIDAD para EC: insertamos "Justicia" en posición alta (después de Farma
# y Tecnología, antes de Salud) — un PL de COIP/CRIMEN ORGANIZADO debería
# ganar contra una eventual mención lateral de salud o trabajo.
PRIORIDAD_EC: list[str] = list(PRIORIDAD)
if "Justicia" not in PRIORIDAD_EC:
    # Después de "Tecnología" (índice 1) para que Justicia gane todos los
    # empates contra categorías genéricas.
    idx = PRIORIDAD_EC.index("Tecnología") + 1
    PRIORIDAD_EC.insert(idx, "Justicia")


# Recompila los patrones con keywords merged
_KW_RE: dict[str, list[re.Pattern]] = {
    cat: [_build_pattern(kw) for kw in kws] for cat, kws in CATEGORIAS.items()
}


def classify(titulo: str | None, sumilla: str | None = None) -> str:
    """Devuelve UN tema (string). Si nada matchea, 'Otros'.

    Usa PRIORIDAD_EC (que es PRIORIDAD de Perú con "Justicia" insertado en
    posición alta) para resolver empates.
    """
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
    for cat in PRIORIDAD_EC:
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


# Exporta constantes y helpers para uso externo.
__all__ = [
    "CATEGORIAS",
    "PRIORIDAD_EC",
    "EXCLUDE_PE",
    "EXTRA_EC",
    "EXTRA_CATEGORIAS_EC",
    "OVERRIDE_DESDE",
    "TECH_MIN_KEYWORDS",
    "classify",
    "count_matches",
    "all_categorias",
]
