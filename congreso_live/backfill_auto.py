"""Backfill automatico de sesiones perdidas.

`vigilar-congreso.yml` solo agarra lo que esta EN VIVO en el momento
exacto que pollea - si el WARP se bloquea (bug recurrente, ver
live_transcribe.py), el job se cae, o detector.py no reconoce el
comite (keyword faltante), la sesion queda perdida para siempre A MENOS
que alguien la note a mano y dispare backfill-vod.yml con el video_id
puntual. Bug real 2026-09-18: 16 sesiones reales (varias de la MISMA
semana en curso) se encontraron y recuperaron asi, a mano, en una sola
sesion de trabajo - Nicolas pidio automatizar esto para no depender de
notarlo cada vez.

Este modulo cierra ese hueco solo: escanea los streams YA TERMINADOS
del canal (mas confiable que la tabla `sesiones` de la API vieja, que
tiene el campo link_video vacio en la enorme mayoria de filas), filtra
los que `sesiones_transcripciones` todavia no tiene, y los recupera -
via captions de YouTube si ya estan listos (rapido, minutos), si no
bajando el audio completo + Whisper (lento, mismo camino que
backfill-vod.yml manual).

No filtra por fecha del titulo: un titulo real puede traer el año mal
escrito (cc_4eBy0KjU, 2026-09-18: "15/09/2025" en vez de 2026) y
filtrar por eso descarta sesiones reales en silencio. En cambio acota
por CANTIDAD de streams recientes (CANDIDATOS_MAX) - los huecos reales
son casi siempre de las ultimas 1-3 semanas.

Uso: python -m congreso_live.cli backfill-auto
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from congreso_live.detector import CANAL, _ydl, clasificar_titulo

log = logging.getLogger(__name__)

CANDIDATOS_MAX = 200
PROCESAR_MAX = 4


def streams_terminados(n: int = CANDIDATOS_MAX) -> list[dict]:
    """Streams was_live (ya terminados, NO en vivo ahora mismo - evita
    chocar con vigilar-congreso.yml capturando algo en curso) del canal
    que son Pleno o comision de interes."""
    with _ydl({"extract_flat": True, "playlistend": n}) as ydl:
        info = ydl.extract_info(CANAL, download=False)
    out: list[dict] = []
    for e in (info.get("entries") or []):
        if not e.get("id") or e.get("live_status") != "was_live":
            continue
        tipo = clasificar_titulo(e.get("title"))
        if not tipo:
            continue
        out.append({"id": e["id"], "titulo": (e.get("title") or "").strip(), "tipo": tipo})
    return out


def encontrar_pendientes(db_path: str | Path) -> list[dict]:
    """Candidatos cuyo video_id todavia NO esta en sesiones_transcripciones."""
    conn = sqlite3.connect(str(db_path))
    try:
        ya = {r[0] for r in conn.execute("SELECT video_id FROM sesiones_transcripciones")}
    except sqlite3.OperationalError:
        ya = set()
    conn.close()
    return [c for c in streams_terminados() if c["id"] not in ya]


def procesar_pendientes(db_path: str | Path, max_n: int = PROCESAR_MAX) -> dict:
    """Recupera hasta `max_n` pendientes: captions primero (rapido), VOD
    completo + Whisper como fallback (lento). Devuelve un resumen para
    loggear en el workflow."""
    from congreso_live.transcripciones import init_schema, obtener_transcripcion
    from noticias.temas import clasificar as clasificar_temas

    todos = encontrar_pendientes(db_path)
    resultado = {"pendientes_totales": len(todos), "procesados": [], "fallidos": []}

    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    for c in todos[:max_n]:
        vid, tipo, titulo_candidato = c["id"], c["tipo"], c["titulo"]
        r = obtener_transcripcion(vid)
        if r:
            temas = clasificar_temas(r["titulo"] or titulo_candidato, r["texto"][:5000])
            conn.execute(
                """INSERT OR REPLACE INTO sesiones_transcripciones
                   (video_id, tipo, titulo, fecha, duracion_seg, texto, temas, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (vid, tipo, r["titulo"] or titulo_candidato, r["fecha"], r["duracion_seg"],
                 r["texto"], ",".join(temas), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            conn.commit()
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


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    """Sin red: prueba que encontrar_pendientes() filtra por video_id ya
    guardado, y que streams_terminados() descarta is_live/is_upcoming y
    titulos que no matchean ningun comite real."""
    import tempfile
    from unittest.mock import patch

    import congreso_live.backfill_auto as ba

    entries = [
        {"id": "A", "title": "EN VIVO: Comision de Salud", "live_status": "was_live"},
        {"id": "B", "title": "EN VIVO: Comision de Salud", "live_status": "is_live"},  # en curso ahora, no tocar
        {"id": "C", "title": "Video institucional sin comision", "live_status": "was_live"},
        {"id": "D", "title": "EN VIVO: Comision de Justicia y Derechos Humanos", "live_status": "was_live"},
    ]
    with patch.object(ba, "_ydl") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.return_value = {"entries": entries}
        candidatos = ba.streams_terminados()
    assert {c["id"] for c in candidatos} == {"A", "D"}, candidatos

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE sesiones_transcripciones (
            video_id TEXT PRIMARY KEY, tipo TEXT, titulo TEXT, fecha TEXT,
            duracion_seg INTEGER, texto TEXT, temas TEXT, fetched_at TEXT)""")
        conn.execute("INSERT INTO sesiones_transcripciones VALUES "
                      "('A','t','tit',NULL,10,'ya la tengo','',NULL)")
        conn.commit()
        conn.close()

        with patch.object(ba, "streams_terminados", lambda: candidatos):
            pendientes = ba.encontrar_pendientes(db_path)
        assert {p["id"] for p in pendientes} == {"D"}, pendientes
    print("OK backfill_auto: filtra en vivo/sin comite y descarta lo ya guardado")


def _test_procesar_pendientes_via_captions():
    """procesar_pendientes() usa captions cuando estan disponibles (no
    llega a intentar el camino VOD, mas lento) y respeta max_n."""
    import tempfile
    from unittest.mock import patch

    import congreso_live.backfill_auto as ba

    candidatos = [
        {"id": "X", "titulo": "Comision de Justicia", "tipo": "Comision: Justicia"},
        {"id": "Y", "titulo": "Comision de Salud", "tipo": "Comision: Salud"},
    ]

    def _fake_obtener(video_id):
        return {"texto": f"transcripcion de {video_id}", "fecha": "2026-09-01",
                "duracion_seg": 100, "titulo": f"titulo real {video_id}"}

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        with patch.object(ba, "encontrar_pendientes", lambda db_path: candidatos), \
             patch("congreso_live.transcripciones.obtener_transcripcion", _fake_obtener):
            resultado = ba.procesar_pendientes(db_path, max_n=1)

        assert resultado["pendientes_totales"] == 2, resultado
        assert len(resultado["procesados"]) == 1, resultado  # max_n=1 respetado
        assert resultado["procesados"][0]["via"] == "captions", resultado

        conn = sqlite3.connect(str(db_path))
        guardado = conn.execute(
            "SELECT texto FROM sesiones_transcripciones WHERE video_id='X'").fetchone()
        conn.close()
        assert guardado == ("transcripcion de X",), guardado
    print("OK backfill_auto: procesar_pendientes usa captions y respeta max_n")


if __name__ == "__main__":
    _demo()
    _test_procesar_pendientes_via_captions()
