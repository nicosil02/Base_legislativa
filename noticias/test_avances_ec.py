import sqlite3
from datetime import datetime, timedelta, timezone

from noticias.avances_ec import noticias_tramite_recientes


def _hace(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        None, _hace(8),
    )])
    out = noticias_tramite_recientes(db, dias=30)
    assert len(out) == 1
    assert "INIAP" in out[0]["titulo"]


def test_excluye_noticia_ceremonial_de_la_misma_fuente():
    # Real: no toda noticia de la Asamblea es de tramite legislativo.
    db = _db([(
        "Portal de la Asamblea Nacional", "EC",
        "Asamblea Nacional conmemora en Riobamba el Día de la Fundación del Ecuador",
        None, _hace(6),
    )])
    assert noticias_tramite_recientes(db, dias=30) == []


def test_excluye_fuentes_de_coyuntura_general():
    # Real: "Coyuntura Politica" es mayormente deportes/policiales - aunque
    # el texto tenga alguna palabra de la lista, si no es una de las fuentes
    # puntuales listadas no deberia colarse.
    db = _db([(
        "Diario Random EC", "EC",
        "Comisión de fiscales avanza en investigación por caso de corrupción",
        None, _hace(1),
    )])
    assert noticias_tramite_recientes(db, dias=30) == []


def test_medio_independiente_sin_ancla_asamblea_no_cuela():
    # "segundo debate en el Concejo" es el Concejo municipal de Quito.
    db = _db([(
        "El Universo", "EC",
        "Regulación de scooters en Quito avanza: falta el veto a la Ley de "
        "Tránsito y el segundo debate en el Concejo",
        None, _hace(3),
    )])
    assert noticias_tramite_recientes(db, dias=30) == []
    # También real: "informe PISA" matchea "informe" pero no tiene nada que
    # ver con tramite legislativo de la Asamblea.
    db2 = _db([(
        "El Comercio", "EC",
        "La brecha real de la educación ecuatoriana tras el informe PISA",
        None, _hace(3),
    )])
    assert noticias_tramite_recientes(db2, dias=30) == []


def test_incluye_medios_independientes_no_solo_la_asamblea():
    # El Comercio y El Universo cuentan como fuente, no solo el RSS de la Asamblea.
    db = _db([(
        "El Universo", "EC",
        "Regulación de scooters en Quito avanza: falta el segundo debate en el pleno",
        None, _hace(3),
    )])
    out = noticias_tramite_recientes(db, dias=30)
    assert len(out) == 1


def test_respeta_ventana_de_dias():
    db = _db([(
        "Portal de la Asamblea Nacional", "EC",
        "Pleno aprueba informe sobre reforma tributaria",
        None, "2025-01-01T00:00:00Z",
    )])
    assert noticias_tramite_recientes(db, dias=7) == []

