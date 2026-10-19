import sqlite3
from datetime import datetime, timezone

from noticias import fuentes_caidas


def _db(tmp_path):
    db = tmp_path / "p.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE noticias_fuentes (id INTEGER, pais TEXT, nombre TEXT, activa INTEGER)")
    c.execute("CREATE TABLE noticias (id INTEGER, fuente_id INTEGER, first_seen_at TEXT)")
    c.executemany("INSERT INTO noticias_fuentes VALUES (?,?,?,?)",
                  [(1, "EC", "Portal Asamblea", 1), (2, "PE", "Viva", 1), (3, "PE", "Muerta hace meses", 1),
                   (4, "PE", "Nunca trajo", 1), (5, "PE", "Apagada", 0)])
    c.executemany("INSERT INTO noticias VALUES (?,?,?)", [
        (1, 1, "2026-10-01T10:00:00Z"), (2, 2, "2026-10-17T10:00:00Z"),
        (3, 3, "2026-06-01T10:00:00Z"), (4, 5, "2026-10-01T10:00:00Z")])
    c.commit(); c.close()
    return str(db)


def test_solo_las_que_traian_algo_y_pararon(tmp_path):
    c = sqlite3.connect(_db(tmp_path))
    ahora = datetime(2026, 10, 18, tzinfo=timezone.utc)
    ultimas = fuentes_caidas.ultimas_actuales(c)
    activas = {f"{p}|{n}" for p, n in c.execute("SELECT pais, nombre FROM noticias_fuentes WHERE activa=1")}
    assert [n for _p, n, _u in fuentes_caidas.caidas(ultimas, activas, ahora)] == ["Portal Asamblea"]


def test_recuerda_la_ultima_aunque_la_purga_borre_las_noticias(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr("congreso_live.notify.enviar_whatsapp", lambda m: None)
    fuentes_caidas.run(db, enviar=False)
    c = sqlite3.connect(db); c.execute("DELETE FROM noticias WHERE fuente_id = 2"); c.commit(); c.close()
    fuentes_caidas.run(db, enviar=False)
    c = sqlite3.connect(db)
    assert "PE|Viva" in fuentes_caidas._leer(c, fuentes_caidas.CLAVE_ULTIMA, {})


def test_avisa_una_sola_vez(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(fuentes_caidas, "caidas", lambda u, a, ahora=None: [("EC", "Portal Asamblea", "2026-10-01")])
    enviados = []
    monkeypatch.setattr("congreso_live.notify.enviar_whatsapp", enviados.append)
    assert len(fuentes_caidas.run(db)) == 1
    assert fuentes_caidas.run(db) == []
    assert len(enviados) == 1 and "Portal Asamblea" in enviados[0]
