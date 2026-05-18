"""Matching de PLs en descripciones de sesiones.

Aproximacion simple: normalizamos el texto (lowercase + sin acentos + sin
puntuacion), tokenizamos en palabras significativas, y buscamos si el
titulo del proyecto aparece como substring de la descripcion de la sesion.

Por que no fuzzy matching: la calidad del texto en las descripciones es
buena (transcripcion directa del titulo oficial del PL), y agregar
rapidfuzz/Levenshtein metro deps por ~95% de precision contra ~80% del
substring simple no vale la pena. Si despues hay falsos negativos
problematicos, agregamos un fallback fuzzy.

Threshold: score = len(titulo) / len(descripcion_window). Solo aceptamos
matches con score >= 0.05 (osea el titulo cubre al menos 5% del texto)
y len(titulo) >= 30 chars para evitar matches espurios de palabras cortas
tipo "Ley de Inquilinato".
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass


@dataclass
class PlMatch:
    n_tramite: str
    titulo: str
    score: float
    match_text: str


def normalize(s: str) -> str:
    """Lowercase + strip acentos + colapsa whitespace + remueve puntuacion comun."""
    if not s:
        return ""
    s = s.lower()
    # Quitar acentos (NFD -> remover combining)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # Reemplazar puntuacion comun por espacio
    s = re.sub(r"[\"\'\.,;:!\?\(\)\[\]\{\}\-_/]", " ", s)
    # Colapsar whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Stopwords cortas frecuentes que no aportan al match
_PL_PREFIX_RE = re.compile(
    r"^(proyecto\s+de\s+|ley\s+|proyecto\s+)",
    re.IGNORECASE,
)


def _titulo_kernel(titulo: str) -> str:
    """Devuelve el "kernel" significativo del titulo para matching.

    El portal Ppless guarda titulos con prefijo tipo "Proyecto de Ley
    Reformatoria a la Ley X". Removemos el prefijo "Proyecto de" y "Ley"
    inicial para que el match sea mas robusto (las descripciones a veces
    dicen "Ley Reformatoria..." sin el "Proyecto de Ley" delante)."""
    norm = normalize(titulo)
    # Remover prefijos comunes iterativamente
    while True:
        new = _PL_PREFIX_RE.sub("", norm, count=1).strip()
        if new == norm:
            break
        norm = new
    return norm


# Tokens "significativos": longitud >= 7 → filtra preposiciones/articulos
# y stopwords cortos sin gastar deps en una lista de stopwords completa.
# "reformatoria"(13), "inquilinato"(11), "educacion"(9) pasan;
# "para"(4), "ley"(3), "con"(3), "esta"(4) no.
_SIGNIFICANT_MIN_LEN = 7


def _significant_tokens(text: str) -> set[str]:
    return {t for t in text.split() if len(t) >= _SIGNIFICANT_MIN_LEN}


def build_idf(rows: list[tuple[str, str]]) -> dict[str, float]:
    """Construye un mapa de IDF (inverse document frequency) sobre los
    titulos de proyectos. Tokens raros (ej "inquilinato") tienen alto peso;
    tokens comunes (ej "organica", "reformatoria") tienen peso bajo.

    Usado por la pasada 2 del matching para ponderar el overlap: que un
    PL comparta "reformatoria" con la sesion no significa nada, pero
    compartir "inquilinato" si.
    """
    import math
    df: dict[str, int] = {}
    n = 0
    for _, titulo in rows:
        kernel = _titulo_kernel(titulo)
        for t in _significant_tokens(kernel):
            df[t] = df.get(t, 0) + 1
        n += 1
    if n == 0:
        return {}
    # IDF estandar suavizado: log((N+1)/(df+1)) + 1
    return {t: math.log((n + 1) / (df_t + 1)) + 1.0 for t, df_t in df.items()}


def find_matches(
    conn: sqlite3.Connection,
    descripcion: str,
    summary: str = "",
    min_titulo_len: int = 20,
    min_score: float = 0.04,
    idf: dict[str, float] | None = None,
    pl_rows: list[tuple[str, str]] | None = None,
) -> list[PlMatch]:
    """Busca PLs referenciados en la descripcion+summary de la sesion.

    Estrategia hibrida (2 pasadas):

    Pasada 1 - SUBSTRING EXACTO (alta confianza):
        El kernel del titulo (sin prefijo "Proyecto de Ley") aparece
        textualmente como substring normalizado del haystack.
        Score = len(kernel) / len(haystack).

    Pasada 2 - TOKEN OVERLAP PONDERADO POR IDF (confianza media):
        Comparamos tokens significativos (len >= 7) pero ponderamos
        cada token por su IDF (raro = peso alto, comun = peso bajo).
        Match si:
          - overlap >= 3 tokens, Y
          - sum(idf de overlap) / sum(idf de kernel) >= 0.65
        Esto evita falsos positivos por compartir solo "organica",
        "reformatoria" o similares que aparecen en cientos de PLs.

    Args:
        conn: conexion a proyectos_ec.db
        descripcion, summary: texto de la sesion
        min_titulo_len: titulos cortos se ignoran
        min_score: ratio minimo de la pasada 1 (substring)
        idf: mapa IDF precalculado (recomendado para rematch batch).
             Si None se calcula on-the-fly (lento si llamas muchas veces).
        pl_rows: lista (n_tramite, titulo) precalculada (mismo motivo).

    Returns:
        Lista de PlMatch ordenada por score desc, sin duplicados.
    """
    haystack = normalize(f"{summary}\n{descripcion}")
    if not haystack:
        return []
    haystack_tokens = _significant_tokens(haystack)
    haylen = max(len(haystack), 1)

    if pl_rows is None:
        pl_rows = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT n_tramite, titulo FROM proyectos "
                "WHERE titulo IS NOT NULL AND length(titulo) >= ?",
                (min_titulo_len,),
            ).fetchall()
        ]
    if idf is None:
        idf = build_idf(pl_rows)

    matches: dict[str, PlMatch] = {}
    for n_tramite, titulo in pl_rows:
        kernel = _titulo_kernel(titulo)
        if len(kernel) < min_titulo_len:
            continue

        # --- Pasada 1b: substring de la "cola distintiva" del titulo ---
        # Muchos titulos empiezan con "ORGANICA REFORMATORIA" o similar y
        # luego mencionan la ley objetivo ("...A LA LEY DE INQUILINATO").
        # La sesion suele nombrar el PL en forma corta ("Ley Reformatoria
        # a la Ley de Inquilinato" sin "ORGANICA"), entonces el substring
        # del kernel COMPLETO falla pero la cola si matchea.
        # Buscamos la cola mas larga de >=18 chars que aparezca en haystack.
        tail = ""
        for bridge in (" a la ley de ", " a la ley ", " al codigo ",
                       " al ", " a la ", " del "):
            idx = kernel.rfind(bridge)
            if idx >= 0:
                candidate = kernel[idx + 1 :]  # incluye el bridge sin space inicial
                if len(candidate) >= 18 and candidate in haystack:
                    if len(candidate) > len(tail):
                        tail = candidate
        if tail:
            score = len(tail) / haylen * 0.8  # ligero descuento vs pasada 1
            if score >= min_score:
                prev = matches.get(n_tramite)
                if prev is None or prev.score < score:
                    matches[n_tramite] = PlMatch(
                        n_tramite=n_tramite, titulo=titulo,
                        score=score, match_text=tail,
                    )
                continue

        # --- Pasada 1: substring exacto ---
        if kernel in haystack:
            score = len(kernel) / haylen
            if score >= min_score:
                prev = matches.get(n_tramite)
                if prev is None or prev.score < score:
                    matches[n_tramite] = PlMatch(
                        n_tramite=n_tramite, titulo=titulo,
                        score=score, match_text=kernel,
                    )
                continue

        # --- Pasada 2: token overlap ponderado por IDF ---
        kernel_tokens = _significant_tokens(kernel)
        if len(kernel_tokens) < 3:
            continue
        overlap = kernel_tokens & haystack_tokens
        if len(overlap) < 3:
            continue
        # Suma de IDF ponderada
        overlap_idf = sum(idf.get(t, 1.0) for t in overlap)
        kernel_idf_total = sum(idf.get(t, 1.0) for t in kernel_tokens)
        if kernel_idf_total <= 0:
            continue
        idf_ratio = overlap_idf / kernel_idf_total
        if idf_ratio < 0.65:
            continue
        # Ademas requerir al menos UN token "raro" (idf >= 2.0) en el overlap.
        # Esto bloquea falsos positivos compuestos solo de palabras comunes.
        if not any(idf.get(t, 1.0) >= 2.0 for t in overlap):
            continue
        score = idf_ratio * 0.5  # ponderacion menor que pasada 1
        prev = matches.get(n_tramite)
        if prev is None or prev.score < score:
            matches[n_tramite] = PlMatch(
                n_tramite=n_tramite, titulo=titulo,
                score=score,
                match_text=" ".join(sorted(overlap))[:200],
            )

    return sorted(matches.values(), key=lambda m: m.score, reverse=True)


# ---------- Extracion de comision + modalidad desde SUMMARY ----------

_MODALIDAD_RE = re.compile(r"\b(virtual|presencial|semi-?presencial|mixta)\b", re.IGNORECASE)
# Encuentra la palabra "Comisión" y captura todo lo que viene despues.
# El procesamiento adicional (cortar en delimitadores, limpiar prefijos)
# se hace en codigo para mantener la regex simple y predecible.
_COMISION_RE = re.compile(r"Comisi[oó]n\s+(.+)", re.IGNORECASE)
# Stopwords del comienzo del nombre extraido (luego de "Comisión ")
_PREFIX_DE_RE = re.compile(r"^(de\s+la\s+|de\s+los\s+|del\s+|de\s+)", re.IGNORECASE)
# Delimitadores que cierran el nombre de la comision (lo que sigue es
# modalidad, lugar, o info adicional que no es parte del nombre)
_COMISION_END_TOKENS = (
    ",", ".", ";",
    " modalidad", " virtual", " presencial", " mixta", " semi-",
    " en ", " - ", " – ",
)


def extract_comision(summary: str) -> str | None:
    """Extrae el nombre de la comision del SUMMARY del VEVENT.

    Ejemplos:
      "Sesión de la Comisión de Justicia, modalidad virtual" -> "Justicia"
      "Sesión Comisión de Educación, modalidad virtual"     -> "Educación"
      "Comisión de Soberanía Alimentaria"                   -> "Soberanía Alimentaria"
      "Sesión de la Comisión de Transparencia y Participación Ciudadana" -> "Transparencia y Participación Ciudadana"
      "Continuación de la sesión N.º 965 del Pleno"         -> "Pleno"
      "Asamblea Nacional del Ecuador"                       -> None
    """
    if not summary:
        return None
    s = summary.strip()
    low = s.lower()
    if "pleno" in low:
        return "Pleno"
    if "comisi" not in low:
        return None
    m = _COMISION_RE.search(s)
    if not m:
        return None
    rest = m.group(1)
    # Cortar en el primer delimitador
    rest_low = rest.lower()
    cut_at = len(rest)
    for tok in _COMISION_END_TOKENS:
        idx = rest_low.find(tok)
        if idx >= 0 and idx < cut_at:
            cut_at = idx
    rest = rest[:cut_at].strip()
    # Limpiar prefijos "de la / del / de"
    rest = _PREFIX_DE_RE.sub("", rest, count=1).strip()
    return rest or None


def extract_modalidad(summary: str, location: str = "") -> str | None:
    """Detecta modalidad (virtual/presencial/mixta) del SUMMARY o LOCATION."""
    text = f"{summary} {location}".lower()
    m = _MODALIDAD_RE.search(text)
    if m:
        val = m.group(1).lower().replace("semipresencial", "semi-presencial")
        return val
    if "virtual" in text:
        return "virtual"
    if "palacio legislativo" in text or "piso" in text:
        return "presencial"
    return None


def strip_modalidad(summary: str) -> str:
    """Limpia el SUMMARY de la cola ", modalidad X" para mostrarlo
    como titulo de sesion sin info redundante."""
    if not summary:
        return ""
    # Cortar en ", modalidad" o ", virtual" / ", presencial"
    s = summary.strip()
    low = s.lower()
    for tok in (", modalidad", ", virtual", ", presencial",
                " modalidad virtual", " modalidad presencial",
                "modalidad virtual", "modalidad presencial"):
        idx = low.find(tok)
        if idx >= 0:
            s = s[:idx].rstrip(" ,.;")
            low = s.lower()
    return s
