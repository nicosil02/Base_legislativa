import sqlite3

from core import db, store, text, tiempo


def test_norm():
    assert text.norm("  Señor  PRESIDENTE, Comisión\n") == "senor presidente, comision"
    assert text.norm(None) == ""


def test_tx_commit_y_rollback(tmp_path):
    d = db.Database(tmp_path / "x.db")
    with d.tx() as c:
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (1)")
    try:
        with d.tx() as c:
            c.execute("INSERT INTO t VALUES (2)")
            raise ValueError
    except ValueError:
        pass
    assert d.conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    d.close()


def test_connect_ro(tmp_path):
    p = tmp_path / "r.db"
    sqlite3.connect(p).executescript("CREATE TABLE t (x); INSERT INTO t VALUES (7);")
    assert db.connect_ro(p).execute("SELECT x FROM t").fetchone()["x"] == 7


def test_store_local(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store._cache.clear()
    assert store.cargar("data/x.json", []) == []
    store.actualizar("data/x.json", lambda d: d + [1], "msg", [])
    assert store.actualizar("data/x.json", lambda d: None, "msg", []) == [1]
    store._cache.clear()
    assert store.cargar("data/x.json", []) == [1]


def test_store_texto_local(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    assert store.leer_texto("c/h.md", "") == ("", None)
    store.actualizar_texto("c/h.md", lambda t: t + "uno\n", "msg")
    store.actualizar_texto("c/h.md", lambda t: t + "dos\n", "msg")
    assert (tmp_path / "c/h.md").read_text(encoding="utf-8") == "uno\ndos\n"


def test_lima():
    assert tiempo.ahora_lima().utcoffset().total_seconds() == -5 * 3600
