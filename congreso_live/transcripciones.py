"""Transcripciones de sesiones (Pleno + comisiones) desde los captions
automaticos de YouTube. YouTube los publica con horas o dias de demora, asi
que esto da transcripciones "al dia siguiente", no en vivo.

Uso:
  python -m congreso_live.cli sync-transcripciones
"""
from __future__ import annotations

import logging
import re
import sqlite3
import urllib.request
from pathlib import Path

from congreso_live.detector import _ydl, con_rotacion_warp, listar_streams
from core.db import db_path as _db_path
from core.db import now_iso
from noticias.temas import clasificar as _clasificar_temas

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _find_db_path() -> Path:
    """proyectos.db (lo importan pages/ y otros paquetes con este nombre)."""
    return _db_path("proyectos.db")


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


def guardar_transcripcion(conn: sqlite3.Connection, video_id: str, tipo: str,
                          titulo: str, fecha: str | None, duracion_seg: int | None,
                          texto: str, temas: list[str]) -> None:
    """Upsert de una fila de sesiones_transcripciones (y commit)."""
    conn.execute(
        """INSERT OR REPLACE INTO sesiones_transcripciones
           (video_id, tipo, titulo, fecha, duracion_seg, texto, temas, fetched_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (video_id, tipo, titulo, fecha, duracion_seg, texto, ",".join(temas), now_iso()),
    )
    conn.commit()


def sesiones_terminadas_recientes(n: int = 20) -> list[dict]:
    """Streams YA TERMINADOS (was_live) de los canales PE y EC que son de
    interes - candidatos a tener transcripcion disponible."""
    return [
        {
            "id": e["id"],
            "titulo": (e.get("title") or "").strip(),
            "tipo": e["_tipo"],
            "url": f"https://www.youtube.com/watch?v={e['id']}",
        }
        for e in listar_streams(n) if e.get("live_status") == "was_live"
    ]


def _limpiar_vtt(vtt_text: str) -> str:
    """Los captions automaticos vienen en VTT 'roll-up': cada bloque repite
    lo ya asentado y agrega una linea nueva. Se toma solo la ultima linea de
    cada bloque para no duplicar texto."""
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
    """Baja y limpia los captions automaticos en español del video. None si
    todavia no estan (normal en sesiones recientes)."""
    def extraer():
        with _ydl({}) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                    download=False)
    try:
        info = con_rotacion_warp(extraer)
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
    """Baja la transcripcion de las sesiones terminadas recientes que todavia
    no estan guardadas. Idempotente."""
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
        guardar_transcripcion(conn, c["id"], c["tipo"], resultado["titulo"] or c["titulo"],
                              resultado["fecha"], resultado["duracion_seg"],
                              resultado["texto"], temas)
        nuevas += 1

    conn.close()
    return {"candidatos": len(candidatos), "pendientes": len(pendientes), "nuevas": nuevas}
