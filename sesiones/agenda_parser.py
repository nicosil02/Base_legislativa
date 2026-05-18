"""Parser del HTML rich-text del orden del dia de una sesion.

Cada `agenda.ordenesDia[].descripcion` viene como HTML con tags `<p>`, `<span>`,
`<strong>`, `<u>`, `<ul>`, `<li>`, entities HTML (`&Oacute;`, `&ntilde;`,
`&deg;`, etc.) y formato de Word generado por el editor del Congreso.

Necesitamos:
1. `to_text(html)` -> texto plano con saltos de linea, sin tags, entities decoded
2. `extract_pls(text)` -> lista de PLs mencionados, con su contexto

Sin dependencias externas: solo `html.parser` y `re` de stdlib.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """Strip HTML tags. Inserta '\n' al cerrar bloques (p, li, br, h*, div)."""

    BLOCK_TAGS = {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                  "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self) -> str:
        return "".join(self.parts)


def to_text(html_str: str | None) -> str:
    """HTML rich -> texto plano. Decode entities, colapsa whitespace."""
    if not html_str:
        return ""
    p = _TextExtractor()
    try:
        p.feed(html_str)
    except Exception:
        # En caso de HTML mal formado, fallback a regex
        return _strip_tags_fallback(html_str)
    txt = p.get_text()
    # Decode entities por si quedo alguna sin procesar
    txt = html.unescape(txt)
    # Normalizar nbsp y whitespace
    txt = txt.replace("\xa0", " ")
    # Colapsar runs de espacios pero preservar newlines
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _strip_tags_fallback(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>|</li>|</div>|</h\d>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


# -------------------------------------------------------------------------
# Extraccion de Proyectos de Ley
#
# Formatos comunes en agendas del Congreso PE:
#   "Proyecto de Ley 14586/2025-CR"
#   "PL N° 14586/2025-CR"
#   "PL 14586/2025-CR"
#   "Proyecto de Ley N° 14586/2025-CR"
#   "Dictamen recaído en el Proyecto de Ley 14586/2025-CR"
#
# El sufijo despues del '-' identifica el proponente:
#   -CR  Congresista
#   -PE  Ejecutivo (Presidencia / Ministerio)
#   -CP  Consejo de Ministros
#   -GR  Gobierno Regional
#   -GL  Gobierno Local
#   -JNJ Junta Nacional de Justicia
#   -BD  Bancada / Banco de Datos
#   ... varios mas
# El sufijo no es critico para nosotros: el pley_num es el identificador en proyectos.
# -------------------------------------------------------------------------

# Disparadores: "Proyecto de Ley", "Proyectos de Ley", "PL", "P.L."
# (con o sin puntos, mayuscula/minuscula).
PL_PATTERN = re.compile(
    r"""
    \b(?:proyectos?\s+de\s+ley|p\.?l\.?)\b   # disparador (PL, P.L., Proyecto/s de Ley)
    \s*(?:n[°ºo\.]+|nro\.?|numero)?         # opcional "N°" / "Nro."
    \s*
    (\d{1,5})                                 # pley_num (con o sin padding)
    \s*[/\-]\s*
    (\d{4})                                   # ano: 2021-2026
    \s*[/\-]?\s*
    ([A-Z]{2,4})?                             # sufijo opcional (-CR, -PE, etc.)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Fallback: PL sin disparador "Proyecto de Ley" pero con formato NNN/YYYY-XX
# (riesgoso: matchea otras referencias numericas). Lo aplicamos *en adicion*
# al pattern principal y luego deduplicamos por pley_num para ser exhaustivos.
PL_PATTERN_LOOSE = re.compile(
    r"\b(\d{4,5})/(\d{4})\s*-?\s*([A-Z]{2,4})\b"
)


def extract_pls(text: str, *, ctx_chars: int = 80) -> list[dict]:
    """Encuentra todas las menciones de Proyectos de Ley en el texto plano.

    Returns lista de dicts {pley_num, ano, sufijo, raw, contexto, start}.
    Deduplica por pley_num (un PL solo aparece una vez en el output, con el
    contexto del primer match).
    """
    if not text:
        return []
    seen: dict[int, dict] = {}
    # Combinar matches del pattern principal + loose. El dedupe por pley_num
    # se encarga de las duplicaciones (ej. "02554" y "2554" son el mismo int).
    matches = list(PL_PATTERN.finditer(text)) + list(PL_PATTERN_LOOSE.finditer(text))
    for m in matches:
        try:
            pley_num = int(m.group(1))
        except (ValueError, TypeError):
            continue
        # Filtrar pley_num implausibles (los del Congreso 2021-2026 van entre 1 y ~15000)
        if pley_num < 1 or pley_num > 30000:
            continue
        ano = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        sufijo = m.group(3) if m.lastindex and m.lastindex >= 3 else None
        start = max(0, m.start() - ctx_chars)
        end = min(len(text), m.end() + ctx_chars)
        ctx = text[start:end].replace("\n", " ").strip()
        raw = m.group(0)
        if pley_num in seen:
            continue
        seen[pley_num] = {
            "pley_num": pley_num,
            "ano": ano,
            "sufijo": sufijo,
            "raw": raw,
            "contexto": ctx,
            "start": m.start(),
        }
    return list(seen.values())


def parse_agenda_punto(html_str: str | None) -> tuple[str, list[dict]]:
    """Atajo: convierte el HTML del punto del orden del dia a (texto_plano, lista_de_PLs)."""
    text = to_text(html_str)
    pls = extract_pls(text)
    return text, pls
