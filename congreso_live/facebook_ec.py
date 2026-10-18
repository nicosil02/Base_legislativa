"""Comisiones de la Asamblea Nacional del Ecuador: transcripcion de las
sesiones que transmiten por Facebook (una pagina por comision).

El listado va con Playwright (yt-dlp no sabe listar paginas de Facebook y el
HTML sin navegador no trae videos); yt-dlp baja el audio y Whisper
transcribe (Facebook no tiene subtitulos). Las terminadas van por
procesar_pendientes (backfill-auto.yml); las que estan EN VIVO las toma
live_transcribe.watch_and_transcribe con listar_en_vivo (vigilar-congreso.yml).
Facebook no bloquea las IPs de GitHub: todo va sin WARP.

Uso: python -m congreso_live.cli comisiones-ec
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# Nombre corto (sesiones_ec.nombre_comision) -> pagina de Facebook.
# Falta Garantias Constitucionales (no tiene pagina propia).
PAGINAS: dict[str, str] = {
    "Seguridad Integral": "ComisionSoberaniaAN",
    "Transparencia y Participación Ciudadana": "profile.php?id=100069440615418",
    "Niñez y Adolescencia": "comisionninezan",
    "Justicia": "JusticiaAN",
    "Biodiversidad": "ComisionBiodiversidad",
    "Desarrollo Económico": "DesarrolloEcAN",
    "Relaciones Internacionales": "RRIIMovilidadAN",
    "Soberanía Alimentaria": "soberanialimen",
    "Derecho a la Salud": "DerechoSaludAN",
    "Régimen Económico": "RegimenEconomAN",
    "Educación": "CECCYT",
    "Gobiernos Autónomos": "GobiAutonomosAN",
    "Derecho al Trabajo": "LaboralAN",
    "Fiscalización": "FiscalizacionAN",
}

# ponytail: solo las N sesiones mas recientes de cada pagina (el listado
# inicial trae ~9, 1-2 semanas). Sin tope el primer backfill encola ~120
# videos de Whisper y tarda semanas en ponerse al dia. Subir si se quiere
# mas historia.
MAX_POR_PAGINA = 3
PREFIJO_ID = "fb_"  # video_id en sesiones_transcripciones, para no chocar con ids de YouTube

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
# Por cada link a /videos/<id>, el texto de su tarjeta: "1:09:24\nSESION No.
# 191-2025-2027 Comision de ...\n504 visualizaciones\n...". Una transmision
# EN VIVO no tiene duracion en la primera linea.
_JS_TARJETAS = r"""()=>{const seen=new Set(),r=[];
for(const a of document.querySelectorAll('a[href*="/videos/"]')){
  const m=a.href.match(/\/videos\/(\d{10,})/); if(!m||seen.has(m[1])) continue; seen.add(m[1]);
  let el=a; for(let i=0;i<8&&el.parentElement;i++){el=el.parentElement; if((el.innerText||'').length>60) break;}
  r.push([m[1], el.innerText||'']);
} return r;}"""
_DURACION = re.compile(r"^\d{1,2}(:\d{2}){1,2}$")
# Primera linea de la tarjeta (o del aro de la foto de perfil) de una
# transmision en vivo; Facebook cambia la palabra segun version e idioma.
_MARCAS_EN_VIVO = {"VIVO", "EN VIVO", "EN DIRECTO", "LIVE", "EN DIRECT"}
# ponytail: si un video terminado tiene menos de esta fraccion de su duracion
# ya transcrita (directo tomado tarde o cortado), se transcribe entero como
# VOD. El directo solo cuenta los segundos con voz, por eso no se pide 100%.
FRACCION_COMPLETA = 0.7


def tipo_de(nombre: str) -> str:
    return f"Comision: {nombre} (EC)"


def url_video(video_id_db: str) -> str:
    """URL publica de un video_id de sesiones_transcripciones (YouTube o fb_)."""
    if video_id_db.startswith(PREFIJO_ID):
        return f"https://www.facebook.com/watch/?v={video_id_db[len(PREFIJO_ID):]}"
    return f"https://www.youtube.com/watch?v={video_id_db}"


def _segundos(duracion: str) -> int:
    """'1:09:24' -> 4164."""
    total = 0
    for parte in duracion.split(":"):
        total = total * 60 + int(parte)
    return total


def parsear_tarjetas(tarjetas: list[list[str]], max_n: int = MAX_POR_PAGINA) -> list[dict]:
    """[[fb_id, texto_tarjeta], ...] -> sesiones YA TERMINADAS (con duracion),
    en el orden de la pagina (mas nueva primero), hasta max_n."""
    out = []
    for fb_id, texto in tarjetas:
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        if len(lineas) < 2 or not _DURACION.match(lineas[0]):
            continue  # en vivo ahora, programada, o tarjeta que no es un video
        out.append({"fb_id": fb_id, "titulo": lineas[1], "duracion_seg": _segundos(lineas[0])})
        if len(out) >= max_n:
            break
    return out


def ids_en_vivo(tarjetas: list[list[str]]) -> list[str]:
    """[[fb_id, texto_tarjeta], ...] -> ids cuya tarjeta empieza con la marca
    de en vivo. Son candidatos: el titulo de la tarjeta no es confiable (el
    aro "VIVO" de la foto de perfil sube hasta el encabezado de la pagina) y
    listar_en_vivo confirma cada uno con info_en_vivo."""
    out: list[str] = []
    for fb_id, texto in tarjetas:
        primera = next((l.strip() for l in texto.splitlines() if l.strip()), "")
        if primera.upper() in _MARCAS_EN_VIVO and fb_id not in out:
            out.append(fb_id)
    return out


def es_directo(url_media: str) -> bool:
    """yt-dlp no marca is_live en Facebook: un directo trae un manifiesto
    DASH .../live-dash/...mpd, un video terminado un .mp4."""
    return "/live-dash/" in url_media


def info_en_vivo(fb_id: str) -> dict | None:
    """{"titulo"} si el video esta transmitiendo ahora, None si no. Un error
    de red se propaga (el que llama decide si eso cuenta como "termino")."""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
        info = y.extract_info(url_video(PREFIJO_ID + fb_id), download=False)
    if not any(es_directo(f.get("manifest_url") or f.get("url") or "") for f in info.get("formats") or []):
        return None
    return {"titulo": (info.get("title") or "").strip()}


def _bajar(url: str) -> bytes:
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": _UA}), timeout=20) as r:
        return r.read()


def alimentar_directo(mpd_url: str, destino, parar) -> None:
    """Escribe en `destino` (el stdin de ffmpeg) el audio de un directo de
    Facebook: el init y despues cada segmento nuevo del manifiesto, desde el
    borde en vivo, hasta que el directo termina o `parar` (threading.Event)
    se activa. Cierra `destino` al salir.
    No se le pasa el .mpd a ffmpeg: su lector DASH pide segmentos del futuro
    y Facebook igual le contesta, ffmpeg sale a 10x tiempo real con audio
    que no es el del directo (probado 2026-10-18)."""
    import time
    import xml.etree.ElementTree as ET
    from urllib.parse import urljoin

    ns = {"m": "urn:mpeg:dash:schema:mpd:2011"}
    ultimo = None
    try:
        while not parar.is_set():
            mpd = ET.fromstring(_bajar(mpd_url))
            if mpd.get("type") != "dynamic":
                break  # el directo termino
            audios = [r for r in mpd.iterfind(".//m:Representation", ns)
                      if r.get("mimeType", "").startswith("audio")]
            tpl = min(audios, key=lambda r: int(r.get("bandwidth") or 0)).find("m:SegmentTemplate", ns)
            # ponytail: Facebook pone t en cada <S>; un manifiesto con r= (repeticiones) no se soporta
            tiempos = [int(s.get("t")) for s in tpl.iterfind("m:SegmentTimeline/m:S", ns)]
            if ultimo is None:
                destino.write(_bajar(urljoin(mpd_url, tpl.get("initialization"))))
                tiempos = tiempos[-1:]  # arrancar en el borde en vivo
            for t in tiempos:
                if ultimo is None or t > ultimo:
                    destino.write(_bajar(urljoin(mpd_url, tpl.get("media").replace("$Time$", str(t)))))
                    ultimo = t
            destino.flush()
            time.sleep(2)  # segmentos de 2 s; el manifiesto guarda 20 s
    except Exception as e:
        if not parar.is_set():
            log.warning("directo de Facebook cortado: %s", e)
    finally:
        try:
            destino.close()
        except Exception:
            pass


def _tarjetas_de_paginas(paginas: dict[str, str], espera_ms: int, timeout_ms: int) -> list[tuple[str, list]]:
    """[(comision, [[fb_id, texto_tarjeta], ...]), ...] de la pestana de
    videos en vivo de cada pagina, con un solo navegador. Una pagina que
    falla queda con lista vacia."""
    from playwright.sync_api import sync_playwright

    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="es-EC", user_agent=_UA)
        for nombre, handle in paginas.items():
            url = (f"https://www.facebook.com/{handle}&sk=live_videos" if handle.startswith("profile.php")
                   else f"https://www.facebook.com/{handle}/live_videos")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(espera_ms)
                tarjetas = page.evaluate(_JS_TARJETAS)
            except Exception as e:
                log.warning("no pude listar Facebook de %s (%s): %s", nombre, handle, e)
                tarjetas = []
            out.append((nombre, tarjetas))
        browser.close()
    return out


def listar_terminadas(paginas: dict[str, str] = PAGINAS) -> list[dict]:
    """Sesiones terminadas recientes de todas las paginas, intercaladas por
    antiguedad (la 1ra de cada comision, despues la 2da de cada una...) para
    que el tope por corrida reparta entre comisiones en vez de vaciar una sola."""
    por_pagina = [[{**s, "comision": nombre} for s in parsear_tarjetas(tarjetas)]
                  for nombre, tarjetas in _tarjetas_de_paginas(paginas, 5000, 45000)]
    return [lista[i] for i in range(MAX_POR_PAGINA) for lista in por_pagina if i < len(lista)]


def listar_en_vivo(paginas: dict[str, str] = PAGINAS) -> list[dict]:
    """Comisiones transmitiendo AHORA, en el formato de
    detector.vivos_de_interes: [{id, titulo, tipo, pais, url}]. Esperas
    cortas: la tarjeta en vivo sale primera."""
    out: list[dict] = []
    for nombre, tarjetas in _tarjetas_de_paginas(paginas, 2500, 20000):
        for fb_id in ids_en_vivo(tarjetas):
            vid = PREFIJO_ID + fb_id
            if vid in {v["id"] for v in out}:
                continue
            try:
                info = info_en_vivo(fb_id)
            except Exception as e:
                log.warning("no pude confirmar el directo %s de %s: %s", fb_id, nombre, e)
                continue
            if info:
                out.append({"id": vid, "titulo": info["titulo"], "tipo": tipo_de(nombre),
                            "pais": "EC", "url": url_video(vid)})
    return out


def _fecha_real(url: str) -> str | None:
    """Fecha (Lima/Quito) en que se transmitio el video. None si falla
    (transcribir_vod usa entonces la fecha de hoy)."""
    from datetime import datetime

    import yt_dlp

    from core.tiempo import LIMA
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
            ts = y.extract_info(url, download=False).get("timestamp")
    except Exception as e:
        log.warning("no pude leer la fecha de %s: %s", url, e)
        return None
    if not ts:
        return None
    return datetime.fromtimestamp(ts, LIMA).date().isoformat()


def procesar_pendientes(db_path: str | Path, max_n: int = 3) -> dict:
    """Transcribe hasta max_n sesiones terminadas que sesiones_transcripciones
    todavia no tiene, o tiene a medias (directo tomado tarde o cortado, ver
    FRACCION_COMPLETA)."""
    from congreso_live.live_transcribe import transcribir_vod
    from congreso_live.transcripciones import init_schema

    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    ya = dict(conn.execute("SELECT video_id, duracion_seg FROM sesiones_transcripciones"))
    conn.close()

    todas = listar_terminadas()
    pendientes = [s for s in todas
                  if (ya.get(PREFIJO_ID + s["fb_id"]) or 0) < FRACCION_COMPLETA * s["duracion_seg"]]
    resultado = {"vistas": len(todas), "pendientes_totales": len(pendientes),
                 "procesados": [], "fallidos": []}
    for s in pendientes[:max_n]:
        vid = PREFIJO_ID + s["fb_id"]
        r = transcribir_vod(vid, tipo_de(s["comision"]), s["titulo"], db_path=db_path,
                            url=url_video(vid), fecha=_fecha_real(url_video(vid)),
                            duracion=s["duracion_seg"])
        (resultado["procesados"] if r["ok"] else resultado["fallidos"]).append(
            {"video_id": vid, "comision": s["comision"], **r})
    return resultado
