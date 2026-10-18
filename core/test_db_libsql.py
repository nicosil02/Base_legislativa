import sqlite3

import pytest

libsql = pytest.importorskip("libsql")

from core.db import _Libsql  # noqa: E402


def test_adaptador_se_comporta_como_sqlite3(tmp_path):
    c = _Libsql(libsql.connect(str(tmp_path / "x.db")))
    c.row_factory = sqlite3.Row
    with c:
        c.execute("CREATE TABLE t (a INTEGER, b TEXT)")
        c.executemany("INSERT INTO t VALUES (?, ?)", [(1, "x"), (2, "y")])
    filas = [r for r in c.execute("SELECT a, b FROM t ORDER BY a")]
    assert filas[0]["b"] == "x" and filas[1][0] == 2 and dict(filas[1]) == {"a": 2, "b": "y"}
    assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    try:
        with c:
            c.execute("INSERT INTO t VALUES (3, 'z')")
            raise ValueError
    except ValueError:
        pass
    assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    c.close()
    assert sqlite3.connect(tmp_path / "x.db").execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
