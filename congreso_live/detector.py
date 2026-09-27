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

# Ecuador (2026-09-26): canal oficial de la Asamblea Nacional (link sacado de
# asambleanacional.gob.ec). Solo el Pleno por ahora - las comisiones EC
# transmiten por Facebook, no aca. Mismo pipeline, misma tabla
# sesiones_transcripciones; se distinguen por TIPO_PLENO_EC.
CANAL_EC = "https://www.youtube.com/@asambleanacionalec/streams"
TIPO_PLENO_EC = "Pleno: Asamblea Nacional (EC)"
# Los titulos reales varian e incluso vienen en ingles ("National Assembly
# Plenary Session No. 120-AN-2025-2029", "Continuacion de la Sesion No.
# 113-AN-...") - el numero de sesion "NNN-AN-AAAA-AAAA" es lo unico estable.
# Deja afuera las Sesiones Solemnes (sin numero), igual que Peru excluye
# ceremonias.
_SESION_EC = re.compile(r"\b\d+-an-\d{4}-\d{4}\b")
# ponytail: tope de streams EC a mirar en backfill - sin esto el primer
# backfill encola ~120 plenos historicos y atrasa los de Peru y la rutina
# de resumenes por dias. Subir si se quiere historia mas vieja.
MAX_EC = 20

# Tokens cortos que aparecen en los titulos de YouTube (no los nombres formales
# largos del catalogo). Si el titulo trae "Comision" + uno de estos -> ordinaria.
#
# Bug real encontrado en vivo 2026-09-16 (Nicolas: "por que no llego a
# capturar la de Desarrollo Agrario?"): 8 de las 25 comisiones ordinarias
# REALES (verificado contra la tabla `sesiones`, fuente de verdad) no
# clasificaban con NINGUN keyword - clasificar_titulo() devolvia None, asi
# que ni siquiera se detectaban como EN VIVO, mucho antes de llegar a
# transcribir nada. Las agregadas abajo (comentario "2026-09-16") cubren
# esas 8; las de arriba quedan igual.
ORDINARIA_KEYWORDS: tuple[str, ...] = (
    "agraria", "ciencia", "comercio exterior", "constitucion", "cultura",
    "defensa del consumidor", "defensa nacional", "descentralizacion",
    "economia", "educacion", "energia y minas", "fiscalizacion",
    "inclusion social", "inteligencia", "justicia", "mujer", "presupuesto",
    "produccion", "pueblos andinos", "relaciones exteriores", "salud",
    "trabajo", "transportes", "vivienda",
    # 2026-09-16: las 8 comisiones reales que no matcheaba ningun keyword
    # de arriba (verificado contra la tabla `sesiones` real, no contra
    # una lista supuesta de 24). "agraria" (femenino) no cubre "Desarrollo
    # Agrario" (masculino) - error de concordancia de genero, no de
    # contenido.
    "agrario", "gestion del estado", "regimenes de excepcion",
    "medio ambiente", "seguimiento legislativo", "procedimientos especiales",
    "etica parlamentaria",
    # 2026-09-18: encontrada al backfillear 8 sesiones reales del Senado
    # que nunca se transcribieron (Nicolas: "creo que hay varias que no
    # tienes") - la Comision de Control Politico sobre los Actos
    # Normativos del Poder Ejecutivo (no-legislativa, catalogo oficial
    # 2026-2027 del Senado) tampoco matcheaba ningun keyword, asi que
    # NUNCA se hubiera detectado en vivo tampoco.
    "control politico",
)

# Marcadores que excluyen un stream aunque diga "comision".
EXCLUIR = (
    # "comision especial" (frase, no solo "especial" suelto) - bug real
    # 2026-09-16: "especial" solo tambien excluia a la comisión ORDINARIA
    # real "Procedimientos Especiales" (el adjetivo modifica
    # "procedimientos", no "comision" - no es una comision especial/ad-hoc).
    "comision especial", "investigadora", "multipartidaria", "subcomision",
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


def clasificar_titulo(titulo: str | None, pais: str = "PE") -> str | None:
    """Devuelve 'Pleno: <camara>', 'Comision: <kw>' o None (no nos interesa).
    Con pais="EC" (canal de la Asamblea) solo reconoce sesiones numeradas
    del Pleno -> TIPO_PLENO_EC.

    El Congreso bicameral (vigente desde 2026) transmite el Pleno de cada
    camara por separado - titulos reales verificados en vivo 2026-09-15:
    "Sesion del Pleno de la Camara de Diputados" y "Sesion del Pleno del
    Senado de la Republica". Una sesion conjunta de ambas camaras (ej.
    mensaje presidencial) no tendria ninguna de esas dos palabras - cae
    al fallback "Pleno: Congreso"."""
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


def es_bloqueo_bot(texto: str | None) -> bool:
    t = texto or ""
    return "not a bot" in t or "429" in t


# Cuantas veces se puede pedir IP nueva a WARP en un mismo proceso - cada
# rotacion tarda ~10 s y, si YouTube bloquea todo WARP, reintentar sin
# tope solo quema tiempo del job.
MAX_ROTACIONES_WARP = 3
_rotaciones_warp = 0


def rotar_warp() -> bool:
    """Pide a WARP una IP de salida nueva (registro nuevo). True si roto.

    El bloqueo "Sign in to confirm you're not a bot" depende de la IP de
    salida de WARP que toque, no de WARP en si: prueba real 2026-09-27
    (_test_bloqueo_yt.yml) - la misma extraccion de video que 30 min antes
    fallaba en backfill-auto (4/4 bloqueados) paso 2/2 por WARP en un runner
    nuevo, y sin WARP fallo 2/2. Es lo mismo que "arreglaba" solo a Peru el
    2026-09-18 al arrancar un job nuevo. Solo corre en CI (YT_DLP_PROXY
    seteado y warp-cli instalado); en local no hace nada."""
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


def listar_streams(n: int) -> list[dict]:
    """Entries flat de los canales PE y EC, cada una con "_pais" y "_tipo"
    (clasificar_titulo) ya puestos - solo las de interes (_tipo no None).
    Un fallo del canal EC se loguea y se sigue (no debe tumbar Peru); uno
    del canal PE se propaga igual que antes (los llamadores ya tratan ese
    caso como fallo transitorio)."""
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

    # Ya filtradas/clasificadas por listar_streams() (lo no-de-interes ni
    # llega hasta aca).
    _c = {"title": "Comision de Salud en vivo", "_tipo": "Comision: Salud", "_pais": "PE"}
    entries = [
        {**_c, "id": "A", "live_status": "is_live"},
        {**_c, "id": "B", "live_status": "is_upcoming"},
        {**_c, "id": "C", "live_status": "was_live"},
        {**_c, "id": "D", "live_status": None},  # sin dato -> fallback
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


def _test_clasificar_ec():
    """Titulos reales del canal de la Asamblea (2026-09-26), incluidos los
    que vienen en ingles."""
    for t in ("Sesión No. 126-AN-2025-2029 del pleno de la Asamblea Nacional",
              "National Assembly Plenary Session No. 120-AN-2025-2029",
              "Virtual Session No. 119-AN-2025-2029 of the National Assembly Plenary",
              "Continuación de la Sesión No. 113-AN-2025-2029 del pleno de la Asamblea Nacional"):
        assert clasificar_titulo(t, "EC") == TIPO_PLENO_EC, t
    assert clasificar_titulo("Sesión Solemne de la Asamblea Nacional - Día de la Fundación", "EC") is None
    # Un titulo de comision del canal EC no debe caer en keywords de Peru.
    assert clasificar_titulo("Comisión de Salud - Asamblea", "EC") is None
    # Peru sin cambios.
    assert clasificar_titulo("Sesion del Pleno del Senado de la Republica") == "Pleno: Senado"
    print("OK detector: clasificacion EC por numero de sesion, Peru intacto")


def _test_rotar_warp():
    """Sin WARP instalado/proxy no hace nada; con ambos, rota hasta el tope
    y despues devuelve False (para que los reintentos no sean infinitos)."""
    from unittest.mock import patch

    import congreso_live.detector as det

    assert det.es_bloqueo_bot("ERROR: Sign in to confirm you're not a bot")
    assert det.es_bloqueo_bot("HTTP Error 429: Too Many Requests")
    assert not det.es_bloqueo_bot("Video unavailable")
    det._rotaciones_warp = 0
    with patch.dict(os.environ, {}, clear=True):
        assert det.rotar_warp() is False
    llamadas = []
    with patch.dict(os.environ, {"YT_DLP_PROXY": "socks5://127.0.0.1:40000"}), \
         patch("shutil.which", lambda _: "/usr/bin/warp-cli"), \
         patch("subprocess.run", lambda args, **kw: llamadas.append(args)), \
         patch.object(det.time, "sleep", lambda s: None):
        rotaciones = [det.rotar_warp() for _ in range(det.MAX_ROTACIONES_WARP + 2)]
    assert rotaciones == [True] * det.MAX_ROTACIONES_WARP + [False, False], rotaciones
    assert ["warp-cli", "--accept-tos", "proxy", "port", "40000"] in llamadas
    det._rotaciones_warp = 0
    print("OK detector: rotar_warp respeta el tope y no hace nada sin WARP")


if __name__ == "__main__":
    _test_rotar_warp()
    _demo()
    _test_vivos_de_interes_usa_live_status_del_flat()
    _test_clasificar_ec()
