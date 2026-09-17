"""Checks de noticias.avances_ec. Correr: python -m noticias.test_avances_ec"""
import sqlite3

from noticias.avances_ec import noticias_tramite_recientes


def _db(rows):
    """rows: lista de (fuente_nombre, pais, titulo, resumen, fecha_pub)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        categoria TEXT, pais TEXT, nombre TEXT)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, fecha_pub TEXT, url TEXT)""")
    fuentes = {}
    for i, (fuente_nombre, pais, titulo, resumen, fecha_pub) in enumerate(rows, start=1):
        if fuente_nombre not in fuentes:
            fid = len(fuentes) + 1
            fuentes[fuente_nombre] = fid
            conn.execute("INSERT INTO noticias_fuentes VALUES (?, 'Institucion', ?, ?)",
                         (fid, pais, fuente_nombre))
        conn.execute(
            "INSERT INTO noticias VALUES (?, ?, ?, ?, ?, ?)",
            (i, fuentes[fuente_nombre], titulo, resumen, fecha_pub, f"https://example.com/{i}"),
        )
    return conn


def test_incluye_noticia_de_tramite_de_la_asamblea():
    db = _db([(
        "Portal de la Asamblea Nacional", "EC",
        "Pleno tramitó en primer debate la normativa para modernizar el INIAP",
        None, "2026-09-09T17:22:28Z",
    )])
    out = noticias_tramite_recientes(db, dias=30)
    assert len(out) == 1
    assert "INIAP" in out[0]["titulo"]


def test_excluye_noticia_ceremonial_de_la_misma_fuente():
    # Real: no toda noticia de la Asamblea es de tramite legislativo.
    db = _db([(
        "Portal de la Asamblea Nacional", "EC",
        "Asamblea Nacional conmemora en Riobamba el Día de la Fundación del Ecuador",
        None, "2026-09-11T02:15:04Z",
    )])
    assert noticias_tramite_recientes(db, dias=30) == []


def test_excluye_fuentes_de_coyuntura_general():
    # Real: "Coyuntura Politica" es mayormente deportes/policiales - aunque
    # el texto tenga alguna palabra de la lista, no es una fuente puntual
    # de la Asamblea y no deberia colarse.
    db = _db([(
        "Diario El Universo", "EC",
        "Comisión de fiscales avanza en investigación por caso de corrupción",
        None, "2026-09-16T12:00:00Z",
    )])
    assert noticias_tramite_recientes(db, dias=30) == []


def test_respeta_ventana_de_dias():
    db = _db([(
        "Portal de la Asamblea Nacional", "EC",
        "Pleno aprueba informe sobre reforma tributaria",
        None, "2025-01-01T00:00:00Z",
    )])
    assert noticias_tramite_recientes(db, dias=7) == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
