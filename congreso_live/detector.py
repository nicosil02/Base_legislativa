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


# Cache de _streams_recientes(): tanto el loop principal de watch_and_transcribe
# como CADA hilo de capturar_y_acumular_en_vivo (al re-chequear si su sesion
# sigue viva) llaman vivos_de_interes() por su cuenta - sin cachear esto,
# con 2-3 sesiones en simultaneo se dispara el listado del canal completo
# varias veces por minuto contra el mismo tunel WARP. Bug real encontrado
# en vivo 2026-09-15 (corrida #760): con el tunel ya cargado, eso satura
# WARP y YouTube empieza a bloquear TODOS los chequeos con "Sign in to
# confirm you're not a bot" - la sesion de Salud estuvo 96 min sin
# transcribirse ni un segundo por esto.
_cache_streams: tuple[float, list[dict]] | None = None
STREAMS_CACHE_TTL_SEG = 50


def _streams_recientes(n: int = 12) -> list[dict]:
    global _cache_streams
    if _cache_streams is not None and (time.time() - _cache_streams[0]) < STREAMS_CACHE_TTL_SEG:
        return _cache_streams[1]
    with _ydl({"extract_flat": True, "playlistend": n}) as ydl:
        info = ydl.extract_info(CANAL, download=False)
    resultado = [e for e in (info.get("entries") or []) if e.get("id")]
    _cache_streams = (time.time(), resultado)
    return resultado


# Cache de resultados de _esta_en_vivo: {video_id: (timestamp, resultado, ok)}.
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
#
# `ok` (tercer campo) distingue un resultado CONFIRMADO (is_live=False
# de verdad) de un chequeo que fallo por excepcion (bot-check, timeout,
# WARP caido) - un fallo transitorio se cachea por FAIL_CACHE_TTL_SEG,
# mucho mas corto, para no amplificar un bloqueo pasajero de WARP en un
# apagon de minutos. Bug real encontrado en vivo 2026-09-15: la corrida
# #760 cacheaba un fallo de red igual que un "no esta en vivo" confirmado
# por 4 min completos, justo cuando WARP mas necesitaba reintentar rapido.
_cache_en_vivo: dict[str, tuple[float, bool, bool]] = {}
CACHE_TTL_SEG = 240
FAIL_CACHE_TTL_SEG = 20


def _esta_en_vivo(video_id: str) -> bool:
    """Confirma is_live con extract completo (flat no lo trae confiable).
    Resultado cacheado por CACHE_TTL_SEG si fue confirmado, o
    FAIL_CACHE_TTL_SEG si el chequeo fallo (ver comentario arriba)."""
    cacheado = _cache_en_vivo.get(video_id)
    if cacheado is not None:
        ttl = CACHE_TTL_SEG if cacheado[2] else FAIL_CACHE_TTL_SEG
        if (time.time() - cacheado[0]) < ttl:
            return cacheado[1]
    try:
        with _ydl({}) as ydl:
            vi = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                  download=False)
        resultado = bool(vi.get("is_live"))
        ok = True
    except Exception as e:
        log.warning("no pude verificar is_live %s: %s", video_id, e)
        resultado = False
        ok = False
    _cache_en_vivo[video_id] = (time.time(), resultado, ok)
    return resultado


def vivos_de_interes() -> list[dict]:
    """Streams del Congreso EN VIVO que son Pleno o comision ordinaria.

    Devuelve list de {id, titulo, tipo, url}. Usa el `live_status` que ya
    trae _streams_recientes() (extraccion flat) - CAUSA RAIZ real del
    bloqueo "Sign in to confirm you're not a bot" encontrada en vivo
    2026-09-15: este codigo hacia un extract_info COMPLETO (_esta_en_vivo)
    por cada uno de los ~6 candidatos, en cada ciclo de 60s - ese patron
    de pedidos repetidos y agresivos es lo que quemaba la reputacion de
    WARP, no un problema de cache/reintentos como se penso primero. El
    listado flat YA trae `live_status` ("is_live"/"is_upcoming"/
    "was_live") con un solo pedido - verificado que coincide con el
    chequeo completo en todos los casos probados, y transcripciones.py ya
    confiaba en el mismo campo para "was_live" sin problema. Bajar de 6+
    pedidos por ciclo a 1 solo corta la saturacion de raiz. _esta_en_vivo
    queda solo como fallback si algun entry no trae el campo."""
    out: list[dict] = []
    for e in _streams_recientes():
        tipo = clasificar_titulo(e.get("title"))
        if not tipo:
            continue
        estado = e.get("live_status")
        if estado is None:
            if not _esta_en_vivo(e["id"]):
                continue
        elif estado != "is_live":
            continue
        out.append({
            "id": e["id"],
            "titulo": (e.get("title") or "").strip(),
            "tipo": tipo,
            "url": f"https://www.youtube.com/watch?v={e['id']}",
        })
    return out


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    """Sin red: prueba que un chequeo OK se cachea por CACHE_TTL_SEG pero
    un chequeo fallido (excepcion) se cachea por FAIL_CACHE_TTL_SEG, mucho
    mas corto - la logica que arreglo el apagon de 96 min del 2026-09-15
    (ver comentario arriba de _esta_en_vivo)."""
    import congreso_live.detector as det

    llamadas = {"n": 0}

    def _ydl_falla_primero(opts):
        class _Fake:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def extract_info(self, url, download=False):
                llamadas["n"] += 1
                if llamadas["n"] == 1:
                    raise RuntimeError("Sign in to confirm you're not a bot")
                return {"is_live": True}
        return _Fake()

    det._cache_en_vivo.clear()
    with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            det, "_ydl", _ydl_falla_primero):
        r1 = det._esta_en_vivo("X1")
        assert r1 is False and llamadas["n"] == 1, "1er chequeo deberia fallar"
        # Recien fallo - con TTL de fallo corto, un 2do intento CASI
        # inmediato deberia reintentar en vez de devolver el cache viejo
        # (a diferencia de un CACHE_TTL_SEG de 240s, que lo hubiera tapado).
        det._cache_en_vivo["X1"] = (
            det._cache_en_vivo["X1"][0] - det.FAIL_CACHE_TTL_SEG - 1,
            det._cache_en_vivo["X1"][1], det._cache_en_vivo["X1"][2],
        )
        r2 = det._esta_en_vivo("X1")
        assert r2 is True and llamadas["n"] == 2, "tras vencer el TTL de fallo, debe reintentar"
        # Ahora que esta OK, un 3er intento INMEDIATO (sin vencer el TTL)
        # debe usar el cache, no volver a pegarle a la red.
        r3 = det._esta_en_vivo("X1")
        assert r3 is True and llamadas["n"] == 2, "un resultado OK reciente debe venir del cache"
    print("OK detector: fallo se cachea corto, exito se cachea largo")


def _test_vivos_de_interes_usa_live_status_del_flat():
    """vivos_de_interes() NO debe llamar a _esta_en_vivo (extract completo)
    cuando el listado flat ya trae live_status - ese era el patron de
    pedidos repetidos que quemaba WARP (ver comentario arriba de la
    funcion). Solo cae a _esta_en_vivo si un entry no trae el campo."""
    from unittest.mock import patch

    import congreso_live.detector as det

    entries = [
        {"id": "A", "title": "Comision de Salud en vivo", "live_status": "is_live"},
        {"id": "B", "title": "Comision de Salud en vivo", "live_status": "is_upcoming"},
        {"id": "C", "title": "Comision de Salud en vivo", "live_status": "was_live"},
        {"id": "D", "title": "Comision de Salud en vivo", "live_status": None},  # sin dato -> fallback
        {"id": "E", "title": "Video sin relacion", "live_status": "is_live"},  # filtrado por titulo, ni se chequea
    ]
    llamadas_esta_en_vivo = []

    def _fake_esta_en_vivo(video_id):
        llamadas_esta_en_vivo.append(video_id)
        return video_id == "D"  # D si esta en vivo, via el fallback

    with patch.object(det, "_streams_recientes", lambda: entries), \
         patch.object(det, "_esta_en_vivo", _fake_esta_en_vivo):
        vivos = det.vivos_de_interes()

    assert llamadas_esta_en_vivo == ["D"], (
        f"solo deberia llamar al fallback para D (sin live_status), llamo: {llamadas_esta_en_vivo}")
    assert {v["id"] for v in vivos} == {"A", "D"}, vivos
    print("OK detector: vivos_de_interes usa live_status del flat, solo cae a extract completo si falta")


if __name__ == "__main__":
    _demo()
    _test_vivos_de_interes_usa_live_status_del_flat()
