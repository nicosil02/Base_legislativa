"""Normalizacion de texto para comparar y buscar palabras clave."""
from __future__ import annotations

import re
import unicodedata


def sin_tildes(s: str) -> str:
    """Quita tildes y dieresis; la ñ queda como n."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str | None) -> str:
    """Minusculas, sin tildes y con espacios simples."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", sin_tildes(s.lower())).strip()
