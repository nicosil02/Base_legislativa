"""Tests de congreso_live/backfill_auto.py (sin red)."""
import sqlite3
from unittest.mock import patch

import congreso_live.backfill_auto as ba
import congreso_live.detector as det


def test_streams_terminados_y_pendientes(tmp_path):
    por_canal = {
        det.CANAL: [
            {"id": "A", "title": "EN VIVO: Comision de Salud", "live_status": "was_live"},
            {"id": "B", "title": "EN VIVO: Comision de Salud", "live_status": "is_live"},  # en curso
            {"id": "C", "title": "Video institucional sin comision", "live_status": "was_live"},
            {"id": "D", "title": "EN VIVO: Comision de Justicia y Derechos Humanos", "live_status": "was_live"},
        ],
        det.CANAL_EC: [
            {"id": "E", "title": "Sesión No. 126-AN-2025-2029 del pleno de la Asamblea Nacional", "live_status": "was_live"},
            {"id": "F", "title": "Sesión Solemne de la Asamblea Nacional", "live_status": "was_live"},
        ],
    }
    with patch.object(det, "_ydl") as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.side_effect = (
            lambda url, download=False: {"entries": por_canal[url]})
        candidatos = ba.streams_terminados()
    assert [c["id"] for c in candidatos] == ["A", "D", "E"]  # Peru primero
    assert candidatos[-1]["tipo"] == det.TIPO_PLENO_EC

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE sesiones_transcripciones (
        video_id TEXT PRIMARY KEY, tipo TEXT, titulo TEXT, fecha TEXT,
        duracion_seg INTEGER, texto TEXT, temas TEXT, fetched_at TEXT)""")
    conn.execute("INSERT INTO sesiones_transcripciones VALUES ('A','t','tit',NULL,10,'ya la tengo','',NULL)")
    conn.commit()
    conn.close()
    with patch.object(ba, "streams_terminados", lambda: candidatos), \
         patch("noticias.videos.pedidos", lambda: []):
        pendientes = ba.encontrar_pendientes(db_path)
    assert {p["id"] for p in pendientes} == {"D", "E"}


def test_procesar_pendientes_via_captions(tmp_path):
    candidatos = [
        {"id": "X", "titulo": "Comision de Justicia", "tipo": "Comision: Justicia"},
        {"id": "Y", "titulo": "Comision de Salud", "tipo": "Comision: Salud"},
    ]

    def fake_obtener(video_id):
        return {"texto": f"transcripcion de {video_id}", "fecha": "2026-09-01",
                "duracion_seg": 100, "titulo": f"titulo real {video_id}"}

    db_path = tmp_path / "test.db"
    with patch.object(ba, "encontrar_pendientes", lambda db_path, solo_pedidos=False: candidatos), \
         patch("congreso_live.transcripciones.obtener_transcripcion", fake_obtener):
        resultado = ba.procesar_pendientes(db_path, max_n=1)
    assert resultado["pendientes_totales"] == 2
    assert len(resultado["procesados"]) == 1  # max_n respetado
    assert resultado["procesados"][0]["via"] == "captions"
    conn = sqlite3.connect(db_path)
    fila = conn.execute("SELECT texto, titulo FROM sesiones_transcripciones WHERE video_id='X'").fetchone()
    conn.close()
    assert fila == ("transcripcion de X", "titulo real X")
