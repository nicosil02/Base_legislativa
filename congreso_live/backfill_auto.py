"""Backfill automatico de sesiones que la captura en vivo se perdio.

Escanea los streams ya terminados del canal (la tabla `sesiones` casi nunca
trae link_video), toma los que sesiones_transcripciones no tiene y los
recupera: captions de YouTube si ya estan, si no VOD completo + Whisper.
Acota por cantidad de streams recientes, no por la fecha del titulo (hay
titulos con el anio mal escrito).

Uso: python -m congreso_live.cli backfill-auto
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from congreso_live.detector import listar_streams

log = logging.getLogger(__name__)

CANDIDATOS_MAX = 200
PROCESAR_MAX = 4


def streams_terminados(n: int = CANDIDATOS_MAX) -> list[dict]:
    """Streams ya terminados (was_live, no los en curso) de interes. Peru
    va primero, asi un hueco de Peru nunca queda detras de EC."""
    return [
        {"id": e["id"], "titulo": (e.get("title") or "").strip(), "tipo": e["_tipo"]}
        for e in listar_streams(n) if e.get("live_status") == "was_live"
    ]


def encontrar_pendientes(db_path: str | Path, solo_pedidos: bool = False) -> list[dict]:
    """Candidatos cuyo video_id todavia NO esta en sesiones_transcripciones."""
    conn = sqlite3.connect(str(db_path))
    try:
        ya = {r[0] for r in conn.execute("SELECT video_id FROM sesiones_transcripciones")}
    except sqlite3.OperationalError:
        ya = set()
    conn.close()
    # Los pedidos manuales (boton en Noticias) van primero: alguien los espera.
    from noticias.videos import pedidos
    candidatos = pedidos() if solo_pedidos else pedidos() + streams_terminados()
    return [c for c in candidatos if c["id"] not in ya]


def procesar_pendientes(db_path: str | Path, max_n: int = PROCESAR_MAX,
                        solo_pedidos: bool = False) -> dict:
    """Recupera hasta `max_n` pendientes: captions primero (rapido), VOD
    completo + Whisper si no (lento). Devuelve un resumen para el log."""
    from congreso_live.transcripciones import (
        guardar_transcripcion, init_schema, obtener_transcripcion,
    )
    from noticias.temas import clasificar as clasificar_temas

    todos = encontrar_pendientes(db_path, solo_pedidos)
    resultado = {"pendientes_totales": len(todos), "procesados": [], "fallidos": []}

    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    for c in todos[:max_n]:
        vid, tipo, titulo_candidato = c["id"], c["tipo"], c["titulo"]
        r = obtener_transcripcion(vid)
        if r:
            temas = clasificar_temas(r["titulo"] or titulo_candidato, r["texto"][:5000])
            guardar_transcripcion(conn, vid, tipo, r["titulo"] or titulo_candidato,
                                  r["fecha"], r["duracion_seg"], r["texto"], temas)
            resultado["procesados"].append({"video_id": vid, "via": "captions", "chars": len(r["texto"])})
            continue

        from congreso_live.live_transcribe import transcribir_vod
        vod = transcribir_vod(vid, tipo, titulo_candidato, db_path=db_path)
        if vod["ok"]:
            resultado["procesados"].append({"video_id": vid, "via": "vod", "chars": vod["chars"]})
        else:
            resultado["fallidos"].append({"video_id": vid, "motivo": vod["motivo"]})
    conn.close()
    return resultado
