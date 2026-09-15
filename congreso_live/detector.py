"""Detecta streams EN VIVO del canal del Congreso y los clasifica.

Solo nos interesan: Pleno y Comisiones Ordinarias (las 24). Se descartan
comisiones especiales/investigadoras/multipartidarias, subcomisiones y los
programas de noticias (Congreso Noticias, etc.).
"""
from __future__ import annotations

import logging
import os
import re
import time
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
    """Devuelve 'Pleno: <camara>', 'Comision: <kw>' o None (no nos interesa).

    El Congreso bicameral (vigente desde 2026) transmite el Pleno de cada
    camara por separado - titulos reales verificados en vivo 2026-09-15:
    "Sesion del Pleno de la Camara de Diputados" y "Sesion del Pleno del
    Senado de la Republica". Una sesion conjunta de ambas camaras (ej.
    mensaje presidencial) no tendria ninguna de esas dos palabras - cae
    al fallback "Pleno: Congreso"."""
    t = _norm(titulo)
    if not t:
        return None
    if any(x in t for x in EXCLUIR):
        return None
    if "pleno" in t:
        if "senado" in t:
            return "Pleno: Senado"
        if "diputados" in t:
            return "Pleno: Diputados"
        return "Pleno: Congreso"
    if "comision" in t:
        for kw in ORDINARIA_KEYWORDS:
            if kw in t:
                return f"Comision: {kw.title()}"
    return None


def _ydl(opts: dict):
    base = {"quiet": True, "no_warnings": True, "skip_download": True}
    # El bloqueo de YouTube a IPs de datacenter (GitHub Actions, Streamlit
    # Cloud) es por reputacion de IP, no por fingerprint de cliente -
    # spoofear el cliente (android/ios) NO lo esquiva (verificado en vivo
    # 2026-09-15, run #1780: mismo error con player_client=android). Lo
    # que si funciona: tunelizar por Cloudflare WARP (VPN gratis, YouTube
    # no la trata como datacenter) - verificado en vivo 2026-09-15
    # (_test_warp.yml run #3: mismo request, sin proxy = bot-check, con
    # proxy WARP = titulo real). YT_DLP_PROXY lo exporta el workflow que
    # instala y arranca WARP en modo proxy (SOCKS5 :40000); en local
    # (IP residencial) no hace falta y la variable no esta seteada.
    proxy = os.environ.get("YT_DLP_PROXY")
    if proxy:
        base["proxy"] = proxy
    base.update(opts)
    return yt_dlp.YoutubeDL(base)


def _streams_recientes(n: int = 12) -> list[dict]:
    with _ydl({"extract_flat": True, "playlistend": n}) as ydl:
        info = ydl.extract_info(CANAL, download=False)
    return [e for e in (info.get("entries") or []) if e.get("id")]


# Cache de resultados de _esta_en_vivo: {video_id: (timestamp, resultado)}.
# watch_and_transcribe() sondea cada poll_seg (60s por default) para
# siempre - sin esto, cada vuelta vuelve a chequear TODOS los candidatos
# de _streams_recientes(), incluyendo los mismos streams ya terminados
# que siguen apareciendo como "recientes" durante horas. Bug real
# encontrado en vivo 2026-09-15: ese volumen de pedidos repetidos al
# mismo puñado de video_ids, via el mismo tunel WARP, hacia que YouTube
# empezara a bloquear con "Sign in to confirm you're not a bot" a los
# pocos minutos - aunque WARP seguia conectado (status "Connected").
# Cachear por CACHE_TTL_SEG corta ese volumen sin afectar la deteccion
# real (una sesion nueva entra en vivo, no aparecia en el cache).
_cache_en_vivo: dict[str, tuple[float, bool]] = {}
CACHE_TTL_SEG = 240


def _esta_en_vivo(video_id: str) -> bool:
    """Confirma is_live con extract completo (flat no lo trae confiable).
    Resultado cacheado por CACHE_TTL_SEG (ver comentario arriba)."""
    cacheado = _cache_en_vivo.get(video_id)
    if cacheado is not None and (time.time() - cacheado[0]) < CACHE_TTL_SEG:
        return cacheado[1]
    try:
        with _ydl({}) as ydl:
            vi = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                  download=False)
        resultado = bool(vi.get("is_live"))
    except Exception as e:
        log.warning("no pude verificar is_live %s: %s", video_id, e)
        resultado = False
    _cache_en_vivo[video_id] = (time.time(), resultado)
    return resultado


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
