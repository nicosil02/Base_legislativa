"""Taxonomía de categorías temáticas para proyectos de ley.

Las keywords se buscan como substring sobre `titulo + sumilla` normalizados
(minúsculas, sin tildes). Un proyecto puede caer en varias categorías.

Editar este archivo cuando se descubran falsos positivos / negativos —
después correr `python -m scraper.cli recategorizar` para re-aplicar.

Categorías cliente-orientadas (basadas en bluebooks de cuentas):
- Tecnología → Google (IA, datos personales, ciberseg, OTT, plataformas).
- Agricultura → Syngenta, Bayer CropScience (plaguicidas, OVM, fertilizantes).
- Salud → Bayer Healthcare, Gilead (medicamentos, hospitales, EsSalud).
- Farma → subcategoría de Salud específica (VIH, hepatitis, oncología, genéricos).
"""
from __future__ import annotations

import re
import unicodedata

CATEGORIAS: dict[str, list[str]] = {
    "Educación": [
        "educa", "universi", "escuela", "colegio", "alumn", "docent",
        "profesor", "magisteri", "minedu", "sineace", "sunedu", "pronabec",
        "instituto pedagóg", "carrera profesional", "currícul",
    ],
    "Agricultura": [
        "agricult", "agrari", "agropecuari", "agroexport", "agroindustri",
        "cultivo", "plaguicid", "pesticid", "agroquímic", "fertilizant",
        "glifosato", "paraquat", "semilla", "ovm", "transgénic",
        "biotecnolog", "moratoria", "riego", "irrigaci", "apicultura",
        "senasa", "midagri", "café", "cacao", "banano", "papa nativa",
        "bioinsum", "herbicida", "fitosanitari", "campesin", "comunidad campesina",
        "agroforester", "agroecolog",
    ],
    "Trabajo": [
        "trabaj", "laboral", "empleo", "remuneraci", "salari", "jornada",
        "sindicat", "contrato de trabajo", "sunafil", "ctsuelo",
        "vacacion", "gratificaci", "indemnizaci",
    ],
    "Banca": [
        "bancari", "banco", "sbs", "crédit", "préstam", "tasa de interés",
        "tarjeta de crédit", "intermediación financiera", "sistema financiero",
        "ahorro", "depósito",
    ],
    "Pensiones": [
        "pension", "afp", "onp", "jubilaci", "retiro de fondos",
        "sistema previsional", "sistema de pensiones",
    ],
    "Control de la actividad privada": [
        "competencia desleal", "antimonopolio", "monopol", "indecopi",
        "supervisión privada", "fiscalizaci", "regulador",
    ],
    "Infraestructura": [
        "infraestructura", "obras públic", "carretera", "puente", "vía",
        "puerto", "aeropuert", "ferroviari", "tren",
    ],
    "Salud": [
        "salud", "minsa", "essalud", "hospital", "enferm", "epidem", "pandem",
        "diagnóstic", "tratamient", "asegurad", "seguro de salud", "atención médic",
        "psicolog", "mental", "discapac", "sanitari", "establecimient de salud",
        "personal de salud", "médic",
    ],
    "Transporte": [
        "transport", "vehícul", "tránsito", "carretera", "licencia de conduc",
        "soat", "transporte público", "transporte de carga",
    ],
    "Pesca": [
        "pesc", "pesquer", "imarpe", "acuicultura", "produce",
        "embarcación pesquera",
    ],
    "Horeca": [
        "hotel", "restauran", "turismo", "gastronom", "alojamient",
        "mincetur", "arrendamiento turístic",
    ],
    "Construcción": [
        "construcci", "edificaci", "ingenierí", "ingenieros del perú",
        "habilitación urbana", "licencia de construcci",
    ],
    "Tributos": [
        "tribut", "impuest", "renta", "igv", "isc", "sunat", "fiscal ",
        "impositiv", "evasión tributaria", "exoneraci", "drawback",
    ],
    "Energía y minas": [
        "energ", "minera", "minería", "minerí", "minem", "petró",
        "gas natural", "hidrocarbur",
    ],
    "Ambiente": [
        "ambient", "ecolog", "deforestaci", "biodivers", "cambio climátic",
        "minam", "ecosistema", "contaminaci", "residuos sólid", "reforestaci",
        "área natural protegida", "humedal",
    ],
    "Transporte y telecomunicaciones": [
        "mtc", "telecomunicaci", "telefon", "espectro radioeléctric",
        "infraestructura de telecomunicaciones",
    ],
    "Deporte": [
        "deport", "ipd", "futbol", "atlet", "olímpic", "panamericano",
    ],
    "Comercio": [
        "comerci", "mercado", "consumidor", "exportac", "importac",
        "aduana", "tlc", "tratado de libre comercio",
    ],
    "Inmobiliario": [
        "inmobiliari", "predi", "registro de la propiedad", "sunarp",
        "vivienda social", "techo propio", "mivivienda",
    ],
    "Informalidad": [
        "informal", "formalizaci", "trabajador independ", "ambulant",
        "comercio ambulatorio",
    ],
    "Minería": [
        "miner", "minerí", "minera", "ingemmet", "minería ilegal",
        "minería artesanal", "reinfo", "concesión minera",
    ],
    "Saneamiento": [
        "saneamient", "agua potabl", "alcantarill", "desagüe", "sedapal",
        "sunass", "acceso al agua",
    ],
    "Energía": [
        "energía eléctrica", "electric", "electricid", "tarifa eléctrica",
        "osinergmin", "energía renovable", "energía solar", "energía eólica",
    ],
    "Telecomunicaciones": [
        "telecomunicaci", "telefonía", "celular", "espectro radioeléctric",
        "osiptel", "fibra óptica", "operador móvil",
    ],
    "Seguros": [
        "aseguradora", "póliza", "seguro contra", "siniestro",
        "compañía de seguros",
    ],
    "Consumo masivo": [
        "consumidor", "consumo", "alimento", "etiquetado", "publicidad engañ",
        "octágono", "rotulado", "código de protección del consumidor",
    ],
    "Mype": [
        "mype", "pyme", "mipyme", "micro empresa", "micro y pequeña empresa",
        "pequeña empresa", "emprendedor",
    ],
    "Tecnología": [
        "tecnolog", "digital", "inteligencia artificial", " ia ", " ia,", " ia.",
        "algoritm", "plataforma digital", "comercio electrónico", "e-commerce",
        "internet", "ciberseg", "ciberdelit", "ciberat", "datos personales",
        "biometr", "redes sociales", "fake news", "desinformaci",
        "derecho al olvido", "gobierno digital", "transformación digital",
        "ciudadanía digital", "brecha digital", "ott", "innovaci",
        "cripto", "blockchain", "firma digital", "identidad digital",
    ],
    "Farma": [
        "farmacéutic", "fármaco", "medicament", "medicamento genérico",
        "biosimilar", "ensayo clínic", "vih", "sida", "hepatitis",
        "vacuna", "digemid", "registro sanitari", "medicamentos esenciales",
        "oncolog", "cáncer", "profilaxis", "antiretroviral", "antiviral",
        "petitorio nacional de medicamentos",
    ],
}


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def _build_pattern(kw: str) -> re.Pattern:
    """Compila una keyword normalizada como regex con frontera de palabra al inicio.

    Esto evita que stems cortos hagan match dentro de palabras: por ejemplo
    'sida' no debe matchear 'univer*sida*d'. La continuación a la derecha queda
    libre (sin \\b) para que stems tipo 'agricult' matcheen 'agricultura',
    'agricultor', etc.
    """
    return re.compile(r"\b" + re.escape(_normalize(kw)))


_KW_RE: dict[str, list[re.Pattern]] = {
    cat: [_build_pattern(kw) for kw in kws] for cat, kws in CATEGORIAS.items()
}


def classify(titulo: str | None, sumilla: str | None = None) -> list[str]:
    """Devuelve la lista de categorías que matchean. Si no matchea ninguna, retorna ['Otros']."""
    text = _normalize(f"{titulo or ''} {sumilla or ''}")
    matched = [cat for cat, patterns in _KW_RE.items() if any(p.search(text) for p in patterns)]
    return matched or ["Otros"]


def all_categorias() -> list[str]:
    """Lista canónica completa (incluye 'Otros')."""
    return list(CATEGORIAS.keys()) + ["Otros"]
