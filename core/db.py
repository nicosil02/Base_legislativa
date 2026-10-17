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


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    """Base de los Database de cada paquete. `with db.tx() as c:` hace
    commit al salir o rollback si hubo excepcion."""

    def __init__(self, path: str | Path):
        self.path = str(Path(path).resolve())
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
