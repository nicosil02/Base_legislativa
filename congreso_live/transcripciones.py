"""Transcripciones de sesiones del Congreso (Pleno + comisiones ordinarias)
a partir de los captions automaticos de YouTube - sin STT propio.

YouTube genera captions automaticos en español para el canal del Congreso,
pero con demora real (un video de 4 dias ya los tenia, uno del mismo dia
todavia no) - esto da transcripciones "al dia siguiente", no en tiempo real.
Verificado en vivo 2026-09-14 contra sesiones reales.

Uso:
  python -m congreso_live.cli sync-transcripciones
"""
from __future__ import annotations

import logging
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp

from congreso_live.detector import CANAL, _ydl, clasificar_titulo
from noticias.temas import clasificar as _clasificar_temas

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _find_db_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [here.parent / "proyectos.db", Path.cwd() / "proyectos.db"]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return candidates[0]


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sesiones_transcripciones (
            video_id TEXT PRIMARY KEY,
            tipo TEXT NOT NULL,
            titulo TEXT NOT NULL,
            fecha TEXT,
            duracion_seg INTEGER,
            texto TEXT NOT NULL,
            temas TEXT,
            fetched_at TEXT NOT NULL
        )
    """)
    conn.commit()


def sesiones_terminadas_recientes(n: int = 20) -> list[dict]:
    """Streams YA TERMINADOS del canal (was_live) que son Pleno o comision
    ordinaria - candidatos a tener transcripcion disponible."""
    with _ydl({"extract_flat": True, "playlistend": n}) as ydl:
        info = ydl.extract_info(CANAL, download=False)
    out = []
    for e in (info.get("entries") or []):
        if not e.get("id") or e.get("live_status") != "was_live":
            continue
        tipo = clasificar_titulo(e.get("title"))
        if not tipo:
            continue
        out.append({
            "id": e["id"],
            "titulo": (e.get("title") or "").strip(),
            "tipo": tipo,
            "url": f"https://www.youtube.com/watch?v={e['id']}",
        })
    return out


def _limpiar_vtt(vtt_text: str) -> str:
    """Los captions automaticos de YouTube vienen en VTT 'roll-up': cada
    bloque repite la(s) linea(s) ya asentada(s) y agrega la nueva linea que
    se esta 'tipeando'. Nos quedamos solo con la ULTIMA linea no vacia de
    cada bloque (la parte nueva) para no duplicar el resto - probado en
    vivo 2026-09-14: un VTT de 792 KB con esta logica da 87 KB de texto
    limpio y coherente, sin la version ingenua (que dejaba cada frase
    repetida 2-3 veces)."""
    bloques = re.split(r"\n\n+", vtt_text)
    salida: list[str] = []
    ultima = None
    for b in bloques:
        b = b.strip()
        if not b or "-->" not in b:
            continue
        cuerpo = "\n".join(l for l in b.splitlines() if "-->" not in l)
        cuerpo = re.sub(r"<[^>]+>", "", cuerpo)
        lineas = [l.strip() for l in cuerpo.splitlines() if l.strip()]
        if not lineas:
            continue
        nueva = lineas[-1]
        if nueva == ultima:
            continue
        salida.append(nueva)
        ultima = nueva
    return " ".join(salida)


def obtener_transcripcion(video_id: str) -> dict | None:
    """Si el video ya tiene captions automaticos en español, los baja y
    limpia. Devuelve None si todavia no estan disponibles (normal para
    sesiones muy recientes - YouTube tarda dias en procesarlos)."""
    try:
        with _ydl({}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                    download=False)
    except Exception as e:
        log.warning("no pude extraer info de %s: %s", video_id, e)
        return None

    auto = info.get("automatic_captions") or {}
    if "es" not in auto:
        return None
    vtt_url = next((f["url"] for f in auto["es"] if f.get("ext") == "vtt"), None)
    if not vtt_url:
        return None

    try:
        req = urllib.request.Request(vtt_url, headers=HEADERS)
        raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    except Exception as e:
        log.warning("no pude bajar VTT de %s: %s", video_id, e)
        return None

    texto = _limpiar_vtt(raw)
    if not texto:
        return None

    upload_date = info.get("upload_date")  # "20260910"
    fecha = None
    if upload_date and len(upload_date) == 8:
        fecha = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

    return {
        "texto": texto,
        "fecha": fecha,
        "duracion_seg": info.get("duration"),
        "titulo": (info.get("title") or "").strip(),
    }


def run_sync(db_path: Path | None = None, max_candidatos: int = 20) -> dict:
    """Chequea sesiones recientes ya terminadas; para las que todavia no
    tienen transcripcion guardada, intenta bajarla. Idempotente: una
    sesion ya guardada no se vuelve a pedir."""
    db_path = db_path or _find_db_path()
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)

    candidatos = sesiones_terminadas_recientes(max_candidatos)
    ya_guardadas = {
        r[0] for r in conn.execute("SELECT video_id FROM sesiones_transcripciones")
    }
    pendientes = [c for c in candidatos if c["id"] not in ya_guardadas]

    nuevas = 0
    for c in pendientes:
        resultado = obtener_transcripcion(c["id"])
        if not resultado:
            continue
        temas = _clasificar_temas(resultado["titulo"], resultado["texto"][:5000])
        conn.execute(
            """INSERT OR REPLACE INTO sesiones_transcripciones
               (video_id, tipo, titulo, fecha, duracion_seg, texto, temas, fetched_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (c["id"], c["tipo"], resultado["titulo"] or c["titulo"],
             resultado["fecha"], resultado["duracion_seg"], resultado["texto"],
             ",".join(temas), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
        nuevas += 1

    conn.close()
    return {"candidatos": len(candidatos), "pendientes": len(pendientes), "nuevas": nuevas}
