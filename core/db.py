"""SQLite: donde esta cada base, conexiones y la clase base de los paquetes."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def db_path(nombre: str = "proyectos.db") -> Path:
    """La base en la raiz del repo; si no esta, la del directorio actual.
    Si no existe ninguna, devuelve la de la raiz (para crearla)."""
    for p in (ROOT / nombre, Path.cwd() / nombre):
        if p.exists():
            return p.resolve()
    return ROOT / nombre


def connect_ro(nombre_o_path: str | Path = "proyectos.db") -> sqlite3.Connection:
    """Solo lectura e inmutable: no crea -wal/-shm (la app no escribe)."""
    p = Path(nombre_o_path)
    if not p.is_absolute() and p.parent == Path("."):
        p = db_path(str(p))
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------------ Turso
# Con TURSO_URL_<BASE> (ej. TURSO_URL_PROYECTOS para proyectos.db) y
# TURSO_TOKEN, conectar() abre una replica local de la base alojada en Turso:
# lee del archivo local y escribe directo en Turso (sin merge ni push de la
# base). Sin esas variables, sqlite3 sobre el archivo como siempre.
# El cliente libsql no tiene row_factory ni cursores iterables: _Libsql los
# agrega para que el resto del codigo no note la diferencia.

class _Fila(tuple):
    """Lo que hace sqlite3.Row: fila[0], fila["col"], fila.keys(), dict(fila)."""

    def __new__(cls, valores, columnas):
        f = super().__new__(cls, valores)
        f._cols = columnas
        return f

    def __getitem__(self, k):
        return super().__getitem__(self._cols.index(k) if isinstance(k, str) else k)

    def keys(self):
        return list(self._cols)


class _Cursor:
    def __init__(self, cur, row_factory):
        self._cur, self._rf = cur, row_factory

    def _fila(self, t):
        if t is None or self._rf is None:
            return t
        cols = [d[0] for d in self._cur.description]
        return _Fila(t, cols) if self._rf is sqlite3.Row else self._rf(self, t)

    def fetchone(self):
        return self._fila(self._cur.fetchone())

    def fetchall(self):
        return [self._fila(t) for t in self._cur.fetchall()]

    def fetchmany(self, n=None):
        return [self._fila(t) for t in self._cur.fetchmany(n or self._cur.arraysize)]

    def __iter__(self):
        return iter(self.fetchall())

    def execute(self, sql, params=()):
        self._cur.execute(sql, params)
        return self

    def executemany(self, sql, filas):
        self._cur.executemany(sql, filas)
        return self

    def __getattr__(self, k):  # description, lastrowid, rowcount, close
        return getattr(self._cur, k)


class _Libsql:
    def __init__(self, conn):
        self._conn = conn
        self.row_factory = None

    def cursor(self):
        return _Cursor(self._conn.cursor(), self.row_factory)

    def execute(self, sql, params=()):
        return _Cursor(self._conn.execute(sql, params), self.row_factory)

    def executemany(self, sql, filas):
        return _Cursor(self._conn.executemany(sql, list(filas)), self.row_factory)

    def __enter__(self):
        return self

    def __exit__(self, tipo, *a):
        self._conn.commit() if tipo is None else self._conn.rollback()

    def __getattr__(self, k):  # commit, rollback, close, executescript, sync
        return getattr(self._conn, k)


def turso_url(nombre: str) -> str | None:
    """URL de Turso para la base `nombre` (proyectos.db -> TURSO_URL_PROYECTOS)."""
    import os
    return os.environ.get("TURSO_URL_" + Path(nombre).stem.upper()) or None


def conectar(nombre: str = "proyectos.db"):
    """Conexion de lectura/escritura a la base: replica de Turso si esta
    configurada (sincronizada al abrir), si no el archivo con sqlite3."""
    url = turso_url(nombre)
    if not url:
        return sqlite3.connect(str(db_path(nombre)))
    import os

    import libsql
    replica = ROOT / "data" / "replica" / Path(nombre).name
    replica.parent.mkdir(parents=True, exist_ok=True)
    conn = libsql.connect(str(replica), sync_url=url, auth_token=os.environ.get("TURSO_TOKEN", ""))
    conn.sync()
    return _Libsql(conn)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    """Base de los Database de cada paquete. `with db.tx() as c:` hace
    commit al salir o rollback si hubo excepcion."""

    def __init__(self, path: str | Path):
        self.path = str(Path(path).resolve())
        if turso_url(Path(path).name):
            self.conn = conectar(Path(path).name)   # escribe en Turso, ver arriba
            self.conn.row_factory = sqlite3.Row
            return
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    @contextmanager
    def tx(self):
        with self.conn:
            yield self.conn
