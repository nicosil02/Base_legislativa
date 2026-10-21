"""Detecta streams EN VIVO del canal del Congreso y los clasifica.

Solo nos interesan: Pleno y Comisiones Ordinarias (las 24). Se descartan
comisiones especiales/investigadoras/multipartidarias, subcomisiones y los
programas de noticias (Congreso Noticias, etc.).
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time

import yt_dlp

from core.text import norm as _norm  # otros paquetes importan detector._norm

log = logging.getLogger(__name__)

CANAL = "https://www.youtube.com/@congresodelarepublicaperu/streams"

# Asamblea Nacional EC: solo el Pleno (las comisiones transmiten por Facebook).
CANAL_EC = "https://www.youtube.com/@asambleanacionalec/streams"
TIPO_PLENO_EC = "Pleno: Asamblea Nacional (EC)"
# Los titulos EC varian (hasta en ingles); el numero "NNN-AN-AAAA-AAAA" es lo
# unico estable. Las Sesiones Solemnes no lo llevan y quedan afuera.
_SESION_EC = re.compile(r"\b\d+-an-\d{4}-\d{4}\b")
# ponytail: tope de streams EC en backfill; sin el, el primer backfill encola
# ~120 plenos historicos y atrasa los de Peru. Subir si se quiere mas historia.
MAX_EC = 20

# Tokens cortos de los titulos de YouTube (no los nombres formales del
# catalogo). "Comision" + uno de estos -> ordinaria. Validar contra la tabla
# `sesiones`: una comision sin keyword aca nunca se detecta en vivo.
ORDINARIA_KEYWORDS: tuple[str, ...] = (
    "agraria", "ciencia", "comercio exterior", "constitucion", "cultura",
    "defensa del consumidor", "defensa nacional", "descentralizacion",
    "economia", "educacion", "energia y minas", "fiscalizacion",
    "inclusion social", "inteligencia", "justicia", "mujer", "presupuesto",
    "produccion", "pueblos andinos", "relaciones exteriores", "salud",
    "trabajo", "transportes", "vivienda",
    # "agraria" no cubre "Desarrollo Agrario" (genero distinto).
    "agrario", "gestion del estado", "regimenes de excepcion",
    "medio ambiente", "seguimiento legislativo", "procedimientos especiales",
    "etica parlamentaria",
    "control politico",
)

# Marcadores que excluyen un stream aunque diga "comision".
EXCLUIR = (
    # La frase entera: "especial" suelto excluiria la ordinaria
    # "Procedimientos Especiales".
    "comision especial", "investigadora", "multipartidaria", "subcomision",
    "noticias", "edicion", "distincion", "homenaje", "ceremonia",
    "conferencia de prensa", "tv digital",
)


EVENTO_KEYWORDS = ("mesa de trabajo", "mesa tecnica", "foro", "conversatorio")
# tema de noticias.temas.clasificar() -> etiqueta en el tipo: Bayer/Syngenta
# (Salud, Agro) y Google/Incode (Tecnologia, Datos y KYC).
MESA_TEMAS = {"Salud": "Salud", "Crop": "Agro", "Tech / Digital": "Tecnologia",
              "KYC / AML / Financiero": "Datos y KYC"}


def clasificar_titulo(titulo: str | None, pais: str = "PE") -> str | None:
    """'Pleno: <camara>', 'Comision: <kw>' o None (no nos interesa).
    Con pais="EC" solo reconoce sesiones numeradas del Pleno -> TIPO_PLENO_EC.
    Una sesion conjunta (sin "senado" ni "diputados") cae en "Pleno: Congreso"."""
    t = _norm(titulo)
    if not t:
        return None
    if pais == "EC":
        return TIPO_PLENO_EC if _SESION_EC.search(t) else None
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
    # Mesas de trabajo/foros (sin "comision" en el titulo): solo si el tema
    # es de interes de un cliente (MESA_TEMAS).
    if any(x in t for x in EVENTO_KEYWORDS):
        from noticias.temas import clasificar
        for tema in clasificar(titulo):
            if tema in MESA_TEMAS:
                return f"Comision: Mesa de trabajo {MESA_TEMAS[tema]}"
    return None


def _ydl(opts: dict):
    base = {"quiet": True, "no_warnings": True, "skip_download": True}
    # YouTube bloquea IPs de datacenter por reputacion (cambiar de cliente no
    # sirve); en CI se sale por Cloudflare WARP, que el workflow expone como
    # YT_DLP_PROXY (SOCKS5). En local no hace falta.
    proxy = os.environ.get("YT_DLP_PROXY")
    if proxy:
        base["proxy"] = proxy
    base.update(opts)
    return yt_dlp.YoutubeDL(base)


def es_bloqueo_bot(texto: str | None) -> bool:
    t = texto or ""
    return "not a bot" in t or "429" in t


# Tope de rotaciones de WARP por proceso: si YouTube bloquea todo WARP,
# reintentar sin tope solo quema tiempo del job.
MAX_ROTACIONES_WARP = 3
_rotaciones_warp = 0


def rotar_warp() -> bool:
    """Pide a WARP una IP de salida nueva (registro nuevo). True si roto.
    El bloqueo "not a bot" depende de la IP de WARP que toque, no de WARP en
    si. Solo actua en CI (YT_DLP_PROXY y warp-cli); en local no hace nada."""
    global _rotaciones_warp
    import shutil
    import subprocess
    from urllib.parse import urlparse

    proxy = os.environ.get("YT_DLP_PROXY")
    if not proxy or not shutil.which("warp-cli") or _rotaciones_warp >= MAX_ROTACIONES_WARP:
        return False
    _rotaciones_warp += 1
    puerto = str(urlparse(proxy).port or 40000)
    for args in (["disconnect"], ["registration", "delete"], ["registration", "new"],
                 ["mode", "proxy"], ["proxy", "port", puerto], ["connect"]):
        subprocess.run(["warp-cli", "--accept-tos", *args], capture_output=True, timeout=60)
    time.sleep(6)
    log.warning("WARP: IP de salida nueva (rotacion %d/%d) tras bloqueo de YouTube",
                _rotaciones_warp, MAX_ROTACIONES_WARP)
    return True


def yt_dlp_cmd(*args: str) -> list[str]:
    """Linea de comandos de yt-dlp, por WARP (YT_DLP_PROXY) si esta."""
    cmd = [sys.executable, "-m", "yt_dlp", *args]
    if os.environ.get("YT_DLP_PROXY"):
        cmd += ["--proxy", os.environ["YT_DLP_PROXY"]]
    return cmd


def con_rotacion_warp(intento, error_de=lambda r: None):
    """Corre intento(); si YouTube bloqueo la IP (por excepcion, o por el
    texto que devuelve error_de(resultado)), rota WARP y reintenta."""
    while True:
        try:
            r = intento()
        except Exception as e:
            if es_bloqueo_bot(str(e)) and rotar_warp():
                continue
            raise
        if es_bloqueo_bot(error_de(r)) and rotar_warp():
            continue
        return r


# Cache del listado del canal: el loop principal y cada hilo de captura
# llaman vivos_de_interes(); sin cache, varias sesiones a la vez saturan WARP
# y YouTube bloquea todos los chequeos.
_cache_streams: tuple[float, list[dict]] | None = None
STREAMS_CACHE_TTL_SEG = 50


def listar_streams(n: int) -> list[dict]:
    """Entries flat de los canales PE y EC de interes, con "_pais" y "_tipo".
    Un fallo del canal EC se loguea y se sigue; uno del canal PE se propaga."""
    out: list[dict] = []
    for pais, url, tope in (("PE", CANAL, n), ("EC", CANAL_EC, min(n, MAX_EC))):
        try:
            with _ydl({"extract_flat": True, "playlistend": tope}) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            if pais == "PE":
                raise
            log.warning("no pude listar el canal %s: %s", pais, e)
            continue
        for e in (info.get("entries") or []):
            tipo = clasificar_titulo(e.get("title"), pais) if e.get("id") else None
            if tipo:
                out.append({**e, "_pais": pais, "_tipo": tipo})
    return out


def _streams_recientes(n: int = 12) -> list[dict]:
    global _cache_streams
    if _cache_streams is not None and (time.time() - _cache_streams[0]) < STREAMS_CACHE_TTL_SEG:
        return _cache_streams[1]
    resultado = listar_streams(n)
    _cache_streams = (time.time(), resultado)
    return resultado


# Cache de _esta_en_vivo: {video_id: (timestamp, resultado, ok)}. Pedir el
# mismo video una y otra vez por WARP termina en bloqueo de YouTube. Un
# chequeo fallido (ok=False) se cachea poco tiempo, para reintentar pronto.
_cache_en_vivo: dict[str, tuple[float, bool, bool]] = {}
CACHE_TTL_SEG = 240
FAIL_CACHE_TTL_SEG = 20


def _esta_en_vivo(video_id: str) -> bool:
    """Confirma is_live con extract completo (solo si el flat no trae
    live_status)."""
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
    """Streams EN VIVO de interes: [{id, titulo, tipo, pais, url}].
    Usa el live_status del listado flat (un solo pedido): un extract completo
    por candidato en cada ciclo quemaba la IP de WARP."""
    out: list[dict] = []
    for e in _streams_recientes():
        tipo = e["_tipo"]
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
            "pais": e["_pais"],
            "url": f"https://www.youtube.com/watch?v={e['id']}",
        })
    return out
