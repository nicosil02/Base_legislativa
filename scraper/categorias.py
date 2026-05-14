"""Taxonomía y clasificador de proyectos de ley en 28 categorías.

Las keywords se aprendieron analizando 14,597 PLs etiquetados manualmente.
Para cada categoría se buscaron los stems con mayor frecuencia Y mayor share
(>=30% de las apariciones de la palabra ocurren en esta categoría).

Estructura:
- `CATEGORIAS`: dict de categoría -> lista de stems (normalizados, sin tildes,
  en minúsculas). Se matchean con word-boundary al inicio para evitar falsos
  positivos del tipo "sida" → "universidad".
- `PRIORIDAD`: orden de desempate cuando dos o más categorías tienen el mismo
  número de matches. Categorías más específicas van primero.
- `classify(titulo, sumilla)` devuelve UN tema (el de mejor score) o "Otros".

Editar este archivo cuando se descubran falsos positivos / negativos. Después
correr `python -m scraper.cli recategorizar` para re-aplicar a la DB local.
Importante: los temas marcados como `manual=1` (importados desde el Excel del
usuario) NO se sobrescriben por el clasificador; sólo afecta a PLs nuevos.
"""
from __future__ import annotations

import re
import unicodedata

# Orden de prioridad de desempate (más específica → más general).
PRIORIDAD: list[str] = [
    # Las categorías cliente-orientadas van primero: cuando un PL tiene
    # keywords de Farma o Tecnología, ganan sobre Salud u Otros.
    "Farma",
    "Tecnología",
    "Pensiones",
    "Pesca",
    "Educación",
    "Minería",
    "Telecomunicaciones",
    "Energía",
    "Salud",
    "Mype",
    "Banca",
    "Tributos",
    "Agricultura",
    "Ambiente",
    "Horeca",
    "Trabajo",
    "Transporte",
    "Seguros",
    "Construcción",
    "Energía y minas",
    "Transporte y telecomunicaciones",
    "Saneamiento",
    "Inmobiliario",
    "Informalidad",
    "Consumo masivo",
    "Control de la actividad privada",
    "Deporte",
    "Comercio",
    "Infraestructura",
    "Otros",
]


# Override: cuando un PL del Excel está etiquetado en alguna categoría origen
# (key) y el clasificador automático detecta fuertemente una categoría
# específica (value), la categoría específica reemplaza al label del Excel.
# Se usa la wildcard "*" para indicar "cualquier categoría del Excel".
#
# Tecnología sobrescribe cualquier categoría — porque hay PLs tech etiquetados
# en Educación, Telecomunicaciones, Comercio, Trabajo, etc. Se exige umbral
# alto (TECH_MIN_KEYWORDS, ver abajo) para evitar robar PLs legítimos.
#
# Farma sobrescribe sólo Otros y Salud (dominio acotado, basta 1 keyword).
OVERRIDE_DESDE: dict[str, list[str]] = {
    "*": ["Tecnología"],
    "Otros": ["Farma"],
    "Salud": ["Farma"],
}

# Umbral mínimo de keywords distintos para que Tecnología sobrescriba una
# categoría legítima del Excel. Como las keywords de Tecnología son muy
# específicas ("inteligencia artificial", "datos personales", "biometr",
# "ciberseg"), basta 1 match para considerar el PL como tech-relevante.
# Subir a 2 si aparecen falsos positivos.
TECH_MIN_KEYWORDS: int = 1


CATEGORIAS: dict[str, list[str]] = {
    "Educación": [
        "educacion", "universidad", "universidades", "universitari",
        "docent", "magisterial", "magisterio", "escuela", "escolar",
        "alumno", "estudiante", "pedagogi", "instituto pedagog",
        "colegio", "minedu", "sineace", "sunedu", "pronabec",
        "curricul", "basica regular", "educacion basica",
        "educativ", "educacion superior", "intercultural",
        "instituciones educativas", "carrera publica magisterial",
    ],
    "Trabajo": [
        "laboral", "trabajador", "remuneraci", "remunerativa",
        "regimen laboral", "regimen del", "regimen especial",
        "régimen cas", "regimen cas", "decreto legislativo 728",
        "decreto legislativo 276", "decreto legislativo 1057",
        "escala remunerativa", "contrato a plazo indeterminado",
        "indeterminado", "productividad", "servidor publico",
        "servidores", "personal asistencial", "personal tecnico",
        "compensacion por tiempo de servicios", "cts del",
        "jornada laboral", "competitividad laboral",
        "sindicato", "sindical", "empleo", "convenios colectivos",
        "negociacion colectiva", "sunafil", "gratificacion",
    ],
    "Salud": [
        # Salud genérico (atención, sistema sanitario, EsSalud, hospitales).
        # Los temas farmacéuticos específicos viven en "Farma" y sobrescriben
        # esta categoría (ver OVERRIDE_DESDE).
        "salud", "essalud", "hospital", "asistencial",
        "personal medico", "personal de salud", "minsa",
        "medico", "medicos", "enfermera", "enfermeria",
        "pacientes", "epidem", "pandem", "diagnostico",
        "establecimiento de salud", "sanitari", "psicolog",
        "discapacidad", "salud mental", "salud ocupacional",
        "atencion medica", "seguro de salud",
    ],
    "Tributos": [
        "impuesto", "impuestos", "renta", "igv", "isc",
        "tributari", "tributario", "tributarios", "fiscal",
        "fiscalizacion", "exoneraci", "drawback", "aduana",
        "selectivo al consumo", "ventas", "contribuyente",
        "recaudacion", "sunat", "tasa impositiva", "predial",
        "infraccion tributaria",
    ],
    "Banca": [
        "financiero", "financiera", "credito", "creditos",
        "banco", "banca", "bancari", "ahorro", "ahorros",
        "deuda", "deudas", "prestamo", "reprogramacion",
        "tasa de interes", "tarjeta de credito", "interes bancario",
        "sistema financiero", "intermediacion financiera",
        "caja municipal", "caja rural", "cooperativa de ahorro",
        "sbs", "reactiva peru",
    ],
    "Pensiones": [
        "pension", "pensiones", "afp", "onp", "snp",
        "previsional", "previsionales", "jubilaci",
        "afiliados", "aportantes", "retiro de fondos",
        "fondos de pensiones", "viudez", "pensionista",
        "administradoras de fondos", "sistema nacional de pensiones",
        "sistema privado de pensiones",
    ],
    "Ambiente": [
        "ambiental", "ambientales", "ambiente", "minam",
        "forestal", "silvestre", "fauna", "biodivers",
        "ecosistema", "ecologi", "contaminaci", "descontaminacion",
        "remediacion", "cambio climatico", "climatico",
        "incendio forestal", "bosque", "deforestaci",
        "area natural protegida", "humedal", "reforestaci",
        "residuos solidos", "mitigacion",
    ],
    "Agricultura": [
        "agricultura", "agricola", "agricolas", "agrario",
        "agrarios", "agraria", "agrarias",
        "agropecuari", "productor agrario", "productores",
        "agricultor", "cafetalero", "ganaderia", "ganadero",
        "cultivo", "siembra", "cosecha", "semilla",
        "agroexportacion", "agroindustria", "agroforesteria",
        "agroecologia", "plaguicid", "pesticid", "agroquimic",
        "fertilizant", "glifosato", "paraquat", "ovm",
        "transgenico", "biotecnologia", "moratoria",
        "riego", "irrigacion", "apicultura", "senasa", "midagri",
        "campesin", "comunidad campesina",
    ],
    "Horeca": [
        "turistic", "turismo", "restauracion", "restaurant",
        "hotel", "alojamient", "gastronom", "mincetur",
        "boleto turistico", "circuito turistico", "valor turistico",
        "puesta en valor", "destino turistico", "arqueologic",
        "museo", "templo", "santuario", "guia de turismo",
        "arrendamiento turistic",
    ],
    "Transporte": [
        "transporte terrestre", "transporte publico", "transporte de carga",
        "transporte aereo", "vehiculo", "vehiculos", "vehicular",
        "transito", "licencia de conducir", "conductor",
        "motocicleta", "mototaxi", "taxi", "automovil",
        "electromovilidad", "pasajeros", "corpac", "atu ",
        "transportista", "pasajes", "soat",
    ],
    "Pesca": [
        "pesca", "pesquera", "pesquero", "pesqueros",
        "pesqueras", "pescador", "pescadores", "acuicultura",
        "embarcacion pesquera", "embarcaciones",
        "produce", "imarpe", "millas marinas",
    ],
    "Construcción": [
        "construccion", "edificacion", "edificaciones",
        "vivienda social", "reconstruccion", "estadio",
        "represa", "habitacional", "ingenierí",
    ],
    "Transporte y telecomunicaciones": [
        "carretera", "vial", "via nacional", "ruta nacional",
        "pavimentacion", "ferrocarril", "tren", "puente",
        "mtc ", "ministerio de transportes",
    ],
    "Energía y minas": [
        "mineral", "minero", "minerales", "gas natural", "hidrocarburos",
        "minem",
    ],
    "Energía": [
        "energia electrica", "electricidad", "tarifa electrica",
        "electrificacion", "petroperu", "petroleo",
        "hidrocarbur", "combustible", "glp", "fise",
        "energia renovable", "energia solar", "energia eolica",
        "osinergmin", "generacion electrica", "masificacion del gas",
    ],
    "Minería": [
        "mineria", "minera", "mineria ilegal", "mineria artesanal",
        "mineria informal", "pequena mineria", "reinfo",
        "concesion minera", "regalia minera", "ingemmet",
    ],
    "Telecomunicaciones": [
        "telecomunicaciones", "telefonia", "telefono",
        "celular", "movil ", "moviles", "internet",
        "radiodifusion", "radio ", "television",
        "espectro radioelectrico", "osiptel", "fibra optica",
        "operador movil",
    ],
    "Comercio": [
        "comercio exterior", "comercio interno",
        "exportacion", "importacion", "aduana", "tlc ",
        "tratado de libre comercio", "zona franca",
        "mercado de", "mercados",
    ],
    "Saneamiento": [
        "saneamiento", "agua potable", "alcantarillado",
        "desague", "sedapal", "sunass",
    ],
    "Control de la actividad privada": [
        "competencia desleal", "antimonopol", "monopol",
        "indecopi", "asamblea constituyente", "referendum",
        "competencia y proteccion", "abuso de posicion dominante",
    ],
    "Infraestructura": [
        "infraestructura publica", "obras publicas",
        "obra publica", "infraestructura nacional",
    ],
    "Mype": [
        "mype", "mypes", "microempresa", "microempresas",
        "micro empresa", "micro y pequena empresa",
        "pequena empresa", "mipyme", "emprendedor",
    ],
    "Inmobiliario": [
        "predio", "predios", "registro de la propiedad",
        "sunarp", "techo propio", "mivivienda",
        "vivienda social",
    ],
    "Informalidad": [
        "informal", "informales", "formalizacion",
        "trabajador independiente", "ambulant",
        "comercio ambulatorio", "posesion informal",
        "titulacion de", "lotes ocupados",
    ],
    "Consumo masivo": [
        "consumidor", "consumidores", "etiquetado",
        "octagono", "rotulado", "publicidad enganos",
        "codigo de proteccion del consumidor",
        "alimento procesado", "bebida", "envase",
    ],
    "Seguros": [
        "aseguradora", "poliza", "seguro contra",
        "siniestro", "compania de seguros",
    ],
    "Deporte": [
        "deporte", "ipd ", "futbol", "atleta",
        "olimpico", "panamericano",
    ],
    # === Categorías cliente-orientadas (sobrescriben Otros y Salud) ===
    "Tecnología": [
        "inteligencia artificial", "ia generativa", "algoritmo",
        "datos personales", "ley 29733", "proteccion de datos",
        "biometr", "biometria", "huella dactilar", "reconocimiento facial",
        "ciberseguridad", "ciberseg", "ciberdelito", "ciberataque",
        "plataforma digital", "comercio electronico", "e-commerce",
        "ecosistema digital", "economia digital", "gobierno digital",
        "transformacion digital", "ciudadania digital", "brecha digital",
        "derecho al olvido", "fake news", "desinformacion", "noticias falsas",
        "ott ", "servicios over the top", "neutralidad de red",
        "cripto", "blockchain", "criptomoneda", "criptoactivo",
        "firma digital", "identidad digital", "identificacion digital",
        "redes sociales",
        "infraestructura digital", "datos abiertos",
        "innovacion tecnologica",
    ],
    "Farma": [
        "medicamento generico", "medicamentos genericos",
        "medicamentos esenciales", "petitorio nacional",
        "biosimilar", "biosimilares", "ensayo clinico", "ensayos clinicos",
        "vih", "vih/sida", "antirretroviral", "antiretroviral",
        "hepatitis b", "hepatitis c", "hepatitis viral",
        "oncologico", "oncologica", "cancer de mama", "cancer triple negativo",
        "quimioterapia", "tratamiento oncologico",
        "vacuna contra", "vacunacion",
        "profilaxis pre exposicion", "profilaxis preexposicion",
        "digemid", "registro sanitario", "patente farmaceutica",
        "farmacia", "farmaceutica", "farmaceutico",
        "industria farmaceutica",
        "medicamento de alto costo", "medicamentos de alto costo",
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
    """Compila el keyword con frontera de palabra al inicio (evita matches
    dentro de palabras, p.ej. 'sida' en 'universidad') y libre a la derecha
    (permite que stems tipo 'agricult' matcheen 'agricultura', 'agricultor')."""
    return re.compile(r"\b" + re.escape(_normalize(kw)))


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
    """Cuenta cuántos keywords de `categoria` matchean en titulo+sumilla.

    Útil para los pases de override que exigen un umbral mínimo (ej. para
    Tecnología sobre categorías legítimas del Excel)."""
    patterns = _KW_RE.get(categoria)
    if not patterns:
        return 0
    text = _normalize(f"{titulo or ''} {sumilla or ''}")
    return sum(1 for p in patterns if p.search(text))


def all_categorias() -> list[str]:
    return list(CATEGORIAS.keys()) + ["Otros"]
