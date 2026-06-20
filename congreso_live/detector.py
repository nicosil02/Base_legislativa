"""Detecta streams EN VIVO del canal del Congreso y los clasifica.

Solo nos interesan: Pleno y Comisiones Ordinarias (las 24). Se descartan
comisiones especiales/investigadoras/multipartidarias, subcomisiones y los
programas de noticias (Congreso Noticias, etc.).
"""
from __future__ import annotations

import logging
import re
import unicodedata

import yt_dlp

log = logging.getLogger(__name__)

CANAL = "https://www.youtube.com/@congresodelarepublicaperu/streams"

# Tokens cortos que aparecen en los titulos de YouTube (no los nombres formales
# largos del catalogo). Si el titulo trae "Comision" + uno de estos -> ordinaria.
ORDINARIA_KEYWORDS: tuple[str, ...] = (
    "agraria", "ciencia", "comercio exterior", "constitucion", "cultura",
    "defensa del consumidor", "defensa nacional", "descentralizacion",
    "economia", "educacion", "energia y minas", "fiscalizacion",
    "inclusion social", "inteligencia", "justicia", "mujer", "presupuesto",
    "produccion", "pueblos andinos", "relaciones exteriores", "salud",
    "trabajo", "transportes", "vivienda",
)

# Marcadores que excluyen un stream aunque diga "comision".
EXCLUIR = (
    "especial", "investigadora", "multipartidaria", "subcomision",
    "noticias", "edicion", "distincion", "homenaje", "ceremonia",
    "conferencia de prensa", "tv digital",
)


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def clasificar_titulo(titulo: str | None) -> str | None:
    """Devuelve 'Pleno', 'Comision: <kw>' o None (no nos interesa)."""
    t = _norm(titulo)
    if not t:
        return None
    if any(x in t for x in EXCLUIR):
        return None
    if "pleno" in t:
        return "Pleno"
    if "comision" in t:
        for kw in ORDINARIA_KEYWORDS:
            if kw in t:
                return f"Comision: {kw.title()}"
    return None


def _ydl(opts: dict):
    base = {"quiet": True, "no_warnings": True, "skip_download": True}
    base.update(opts)
    return yt_dlp.YoutubeDL(base)


def _streams_recientes(n: int = 12) -> list[dict]:
    with _ydl({"extract_flat": True, "playlistend": n}) as ydl:
        info = ydl.extract_info(CANAL, download=False)
    return [e for e in (info.get("entries") or []) if e.get("id")]


def _esta_en_vivo(video_id: str) -> bool:
    """Confirma is_live con extract completo (flat no lo trae confiable)."""
    try:
        with _ydl({}) as ydl:
            vi = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                  download=False)
        return bool(vi.get("is_live"))
    except Exception as e:
        log.warning("no pude verificar is_live %s: %s", video_id, e)
        return False


def vivos_de_interes() -> list[dict]:
    """Streams del Congreso EN VIVO que son Pleno o comision ordinaria.

    Devuelve list de {id, titulo, tipo, url}. Hace extract completo solo para
    los pocos candidatos que pasan el filtro de titulo (barato)."""
    out: list[dict] = []
    for e in _streams_recientes():
        tipo = clasificar_titulo(e.get("title"))
        if not tipo:
            continue
        if not _esta_en_vivo(e["id"]):
            continue
        out.append({
            "id": e["id"],
            "titulo": (e.get("title") or "").strip(),
            "tipo": tipo,
            "url": f"https://www.youtube.com/watch?v={e['id']}",
        })
    return out
