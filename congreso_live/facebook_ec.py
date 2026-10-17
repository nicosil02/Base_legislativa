"""Comisiones de la Asamblea Nacional del Ecuador: transcripcion de las
sesiones que transmiten por Facebook (una pagina por comision).

El listado va con Playwright (yt-dlp no sabe listar paginas de Facebook y el
HTML sin navegador no trae videos); yt-dlp baja el audio y Whisper
transcribe (Facebook no tiene subtitulos). Solo sesiones ya terminadas.

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


def tipo_de(nombre: str) -> str:
    return f"Comision: {nombre} (EC)"


def url_video(video_id_db: str) -> str:
    """URL publica de un video_id de sesiones_transcripciones (YouTube o fb_)."""
    if video_id_db.startswith(PREFIJO_ID):
        return f"https://www.facebook.com/watch/?v={video_id_db[len(PREFIJO_ID):]}"
    return f"https://www.youtube.com/watch?v={video_id_db}"


def parsear_tarjetas(tarjetas: list[list[str]], max_n: int = MAX_POR_PAGINA) -> list[dict]:
    """[[fb_id, texto_tarjeta], ...] -> sesiones YA TERMINADAS (con duracion),
    en el orden de la pagina (mas nueva primero), hasta max_n."""
    out = []
    for fb_id, texto in tarjetas:
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        if len(lineas) < 2 or not _DURACION.match(lineas[0]):
            continue  # en vivo ahora, programada, o tarjeta que no es un video
        out.append({"fb_id": fb_id, "titulo": lineas[1]})
        if len(out) >= max_n:
            break
    return out


def listar_terminadas(paginas: dict[str, str] = PAGINAS) -> list[dict]:
    """Sesiones terminadas recientes de todas las paginas, intercaladas por
    antiguedad (la 1ra de cada comision, despues la 2da de cada una...) para
    que el tope por corrida reparta entre comisiones en vez de vaciar una sola."""
    from playwright.sync_api import sync_playwright

    por_pagina: list[list[dict]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="es-EC", user_agent=_UA)
        for nombre, handle in paginas.items():
            url = (f"https://www.facebook.com/{handle}&sk=live_videos" if handle.startswith("profile.php")
                   else f"https://www.facebook.com/{handle}/live_videos")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
                sesiones = parsear_tarjetas(page.evaluate(_JS_TARJETAS))
            except Exception as e:
                log.warning("no pude listar Facebook de %s (%s): %s", nombre, handle, e)
                sesiones = []
            por_pagina.append([{**s, "comision": nombre} for s in sesiones])
        browser.close()
    return [lista[i] for i in range(MAX_POR_PAGINA) for lista in por_pagina if i < len(lista)]


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
    todavia no tiene."""
    from congreso_live.live_transcribe import transcribir_vod
    from congreso_live.transcripciones import init_schema

    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    ya = {r[0] for r in conn.execute("SELECT video_id FROM sesiones_transcripciones")}
    conn.close()

    todas = listar_terminadas()
    pendientes = [s for s in todas if PREFIJO_ID + s["fb_id"] not in ya]
    resultado = {"vistas": len(todas), "pendientes_totales": len(pendientes),
                 "procesados": [], "fallidos": []}
    for s in pendientes[:max_n]:
        vid = PREFIJO_ID + s["fb_id"]
        r = transcribir_vod(vid, tipo_de(s["comision"]), s["titulo"], db_path=db_path,
                            url=url_video(vid), fecha=_fecha_real(url_video(vid)))
        (resultado["procesados"] if r["ok"] else resultado["fallidos"]).append(
            {"video_id": vid, "comision": s["comision"], **r})
    return resultado
