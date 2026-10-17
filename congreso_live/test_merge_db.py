"""Tests de congreso_live/merge_db.py."""
import sqlite3

from congreso_live.merge_db import merge_sesiones

_TABLA = """CREATE TABLE sesiones_transcripciones (
    video_id TEXT PRIMARY KEY, tipo TEXT, titulo TEXT, fecha TEXT,
    duracion_seg INTEGER, texto TEXT, temas TEXT, fetched_at TEXT)"""


def _db(path, *filas):
    c = sqlite3.connect(path)
    c.execute(_TABLA)
    c.executemany("INSERT INTO sesiones_transcripciones VALUES (?,'t','tit',NULL,?,?,'',NULL)", filas)
    c.commit()
    c.close()


def test_agrega_nuevas_sin_pisar_las_mas_completas(tmp_path):
    b, d = str(tmp_path / "base.db"), str(tmp_path / "donor.db")
    _db(b, ("A", 10, "hola"))
    _db(d, ("B", 20, "chau"), ("A", 10, "ho"))  # A con menos texto: no pisa
    merge_sesiones(b, d)
    c = sqlite3.connect(b)
    filas = dict(c.execute("SELECT video_id, texto FROM sesiones_transcripciones"))
    c.close()
    assert filas == {"A": "hola", "B": "chau"}
