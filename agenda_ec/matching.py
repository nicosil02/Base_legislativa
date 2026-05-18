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


def find_matches(
    conn: sqlite3.Connection,
    descripcion: str,
    summary: str = "",
    min_titulo_len: int = 30,
    min_score: float = 0.04,
) -> list[PlMatch]:
    """Busca PLs cuyo titulo aparece (como substring normalizado) en la
    descripcion + summary de la sesion.

    Args:
        conn: conexion a proyectos_ec.db (con tabla proyectos)
        descripcion: texto plano (ya unescapado) de la DESCRIPTION del VEVENT
        summary: texto del SUMMARY (concatenado al haystack)
        min_titulo_len: titulos mas cortos se ignoran (evita falsos positivos)
        min_score: ratio minimo len(titulo) / len(haystack) para aceptar

    Returns:
        Lista de PlMatch, ordenada por score desc, sin duplicados de n_tramite.
    """
    haystack = normalize(f"{summary}\n{descripcion}")
    if not haystack:
        return []

    rows = conn.execute(
        "SELECT n_tramite, titulo FROM proyectos WHERE titulo IS NOT NULL AND length(titulo) >= ?",
        (min_titulo_len,),
    ).fetchall()

    matches: dict[str, PlMatch] = {}  # n_tramite -> mejor match
    haylen = max(len(haystack), 1)
    for row in rows:
        n_tramite = row[0]
        titulo = row[1]
        kernel = _titulo_kernel(titulo)
        if len(kernel) < min_titulo_len:
            continue
        if kernel in haystack:
            score = len(kernel) / haylen
            if score < min_score:
                continue
            prev = matches.get(n_tramite)
            if prev is None or prev.score < score:
                matches[n_tramite] = PlMatch(
                    n_tramite=n_tramite,
                    titulo=titulo,
                    score=score,
                    match_text=kernel,
                )

    return sorted(matches.values(), key=lambda m: m.score, reverse=True)


# ---------- Extracion de comision + modalidad desde SUMMARY ----------

_MODALIDAD_RE = re.compile(r"\b(virtual|presencial|semi-?presencial|mixta)\b", re.IGNORECASE)
_COMISION_RE = re.compile(
    r"(?:Ses[ií]on\s+(?:de\s+la\s+)?Comisi[oó]n(?:\s+de\s+la\s+)?\s+(?:de\s+|del\s+)?)"
    r"(.+?)(?:[\.,]|$|modalidad|virtual|presencial)",
    re.IGNORECASE,
)


def extract_comision(summary: str) -> str | None:
    """Extrae el nombre de la comision del SUMMARY.

    Ejemplos:
      "Sesión de la Comisión de Justicia, modalidad virtual" -> "Justicia"
      "Sesión Comisión de Educación, modalidad virtual"       -> "Educación"
      "Continuación de la sesión N.º 965 del Pleno"           -> "Pleno"
    """
    if not summary:
        return None
    if "pleno" in summary.lower():
        return "Pleno"
    m = _COMISION_RE.search(summary)
    if m:
        nombre = m.group(1).strip().rstrip(",;.")
        return nombre or None
    return None


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
