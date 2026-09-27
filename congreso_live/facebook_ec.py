"""Comisiones de la Asamblea Nacional del Ecuador: transcripcion de sus
sesiones, que transmiten por Facebook (una pagina por comision), no por
YouTube como el Pleno.

Verificado 2026-09-27, desde GitHub Actions (IP de datacenter, sin login,
sin WARP): Playwright ve el listado /live_videos de cada pagina y yt-dlp
baja el audio de cada video. yt-dlp NO sabe listar paginas de Facebook
("Unsupported URL") y el HTML crudo sin navegador no trae ningun video -
por eso el listado va con Playwright.

Sin subtitulos en español en Facebook: se transcribe siempre con Whisper
(mismo camino que el backfill de VOD de Peru). Solo sesiones YA
TERMINADAS - la captura en vivo por Facebook queda para despues.

Uso: python -m congreso_live.cli comisiones-ec
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# Nombre corto (el de sesiones_ec.nombre_comision de la agenda EC) -> pagina
# de Facebook. Cada una verificada a mano 2026-09-27: titulo oficial de la
# pagina + videos en vivo de sesiones recientes. Falta Garantias
# Constitucionales (no aparece pagina propia en la busqueda de Facebook).
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
    """Fecha (Lima/Quito, UTC-5) en que se transmitio el video. None si
    falla - transcribir_vod cae a la fecha de hoy, que en una sesion
    procesada el mismo dia es la correcta igual."""
    from datetime import datetime, timedelta, timezone

    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
            ts = y.extract_info(url, download=False).get("timestamp")
    except Exception as e:
        log.warning("no pude leer la fecha de %s: %s", url, e)
        return None
    if not ts:
        return None
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=-5))).date().isoformat()


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


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    """Sin red: tarjetas con el texto real de la pagina (2026-09-27)."""
    tarjetas = [
        ["111", "EN DIRECTO\nSesión No. 193-2025-2027 Comisión de Desarrollo Económico\n12 espectadores"],
        ["222", "23:20\nSesión Nro. 192-2025-2027 Comisión de Desarrollo Económico\n528 visualizaciones\n · hace 2 días"],
        ["333", "1:09:24\nSESIÓN No. 191-2025-2027 Comisión de Desarrollo Económico\n504 visualizaciones"],
        ["444", "1:46:23\nSesión No. 190-2025-2027 Comisión de Desarrollo Económico\n1,1 mil visualizaciones"],
        ["555", "42:47\nSesión Nro. 189-2025-2027\n678 visualizaciones"],
    ]
    s = parsear_tarjetas(tarjetas, max_n=3)
    assert [x["fb_id"] for x in s] == ["222", "333", "444"], s  # salta la EN DIRECTO, respeta el tope
    assert s[0]["titulo"].startswith("Sesión Nro. 192"), s
    assert url_video("fb_222") == "https://www.facebook.com/watch/?v=222"
    assert url_video("ZEUaL91M6D4").startswith("https://www.youtube.com/")
    assert tipo_de("Justicia") == "Comision: Justicia (EC)"
    print("OK facebook_ec: salta sesiones en vivo, respeta el tope y arma URLs/tipos")


if __name__ == "__main__":
    _demo()
