"""Schema y wrapper para mesas_tecnicas en proyectos.db."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS mesas_tecnicas (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  url             TEXT UNIQUE NOT NULL,
  titulo          TEXT,                  -- titulo del RSS ("Mesa de trabajo", "Ceremonia", etc.)
  tipo            TEXT,                  -- igual al titulo, normalizado
  tema            TEXT,                  -- descripcion del proposito del evento
  fecha           TEXT,                  -- YYYY-MM-DD del evento (si la extraemos)
  hora            TEXT,                  -- "11:00 AM"
  organiza        TEXT,                  -- "Congresista X (Bancada Y)"
  congresista     TEXT,                  -- nombre del congresista organizador
  bancada         TEXT,                  -- bancada/grupo parlamentario
  comision        TEXT,                  -- comision si menciona alguna
  lugar           TEXT,
  pub_date        TEXT,                  -- pubDate del RSS (cuando se publico el post)
  first_seen_at   TEXT NOT NULL,
  last_seen_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mt_fecha ON mesas_tecnicas(fecha);
CREATE INDEX IF NOT EXISTS idx_mt_tipo ON mesas_tecnicas(tipo);
CREATE INDEX IF NOT EXISTS idx_mt_pub ON mesas_tecnicas(pub_date);

CREATE TABLE IF NOT EXISTS mesas_tecnicas_sync_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  vistos        INTEGER DEFAULT 0,
  nuevos        INTEGER DEFAULT 0,
  actualizados  INTEGER DEFAULT 0,
  paginas_rss   INTEGER DEFAULT 0,
  errores       INTEGER DEFAULT 0,
  mensaje       TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
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
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def init_schema(self) -> None:
        with self.tx() as c:
            c.executescript(SCHEMA)
            # Migracion idempotente: agregar tema si no existe (para DBs viejas)
            try:
                cols = [r[1] for r in c.execute("PRAGMA table_info(mesas_tecnicas)")]
                if "tema" not in cols:
                    c.execute("ALTER TABLE mesas_tecnicas ADD COLUMN tema TEXT")
            except Exception:
                pass

    def upsert(self, row: dict) -> tuple[bool, bool]:
        """Insert si no existe, update si cambio. Devuelve (is_new, changed)."""
        url = row["url"]
        now = now_iso()
        existing = self.conn.execute(
            "SELECT titulo, tipo, tema, fecha, hora, organiza, congresista, "
            "bancada, comision, lugar, pub_date FROM mesas_tecnicas WHERE url = ?",
            (url,),
        ).fetchone()
        if existing is None:
            with self.tx() as c:
                c.execute(
                    """INSERT INTO mesas_tecnicas
                       (url, titulo, tipo, tema, fecha, hora, organiza, congresista,
                        bancada, comision, lugar, pub_date,
                        first_seen_at, last_seen_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (url, row.get("titulo"), row.get("tipo"), row.get("tema"),
                     row.get("fecha"), row.get("hora"), row.get("organiza"),
                     row.get("congresista"), row.get("bancada"),
                     row.get("comision"), row.get("lugar"),
                     row.get("pub_date"), now, now),
                )
            return True, True

        # Detectar cambios reales (cualquier campo distinto)
        changed = False
        for k in ("titulo", "tipo", "tema", "fecha", "hora", "organiza",
                  "congresista", "bancada", "comision", "lugar", "pub_date"):
            new_v = row.get(k)
            old_v = existing[k] if k in existing.keys() else None
            if (new_v or None) != (old_v or None):
                changed = True
                break

        with self.tx() as c:
            if changed:
                c.execute(
                    """UPDATE mesas_tecnicas SET
                       titulo=?, tipo=?, tema=?, fecha=?, hora=?, organiza=?,
                       congresista=?, bancada=?, comision=?, lugar=?, pub_date=?,
                       last_seen_at=?
                       WHERE url=?""",
                    (row.get("titulo"), row.get("tipo"), row.get("tema"),
                     row.get("fecha"), row.get("hora"), row.get("organiza"),
                     row.get("congresista"), row.get("bancada"),
                     row.get("comision"), row.get("lugar"),
                     row.get("pub_date"), now, url),
                )
            else:
                c.execute(
                    "UPDATE mesas_tecnicas SET last_seen_at=? WHERE url=?",
                    (now, url),
                )
        return False, changed

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM mesas_tecnicas").fetchone()[0]

    def start_sync_run(self) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO mesas_tecnicas_sync_runs (started_at) VALUES (?)",
                (now_iso(),),
            )
            return cur.lastrowid

    def finish_sync_run(self, run_id: int, **kwargs) -> None:
        cols = ["finished_at=?"]
        vals = [now_iso()]
        for k, v in kwargs.items():
            cols.append(f"{k}=?")
            vals.append(v)
        vals.append(run_id)
        with self.tx() as c:
            c.execute(
                f"UPDATE mesas_tecnicas_sync_runs SET {', '.join(cols)} WHERE id=?",
                vals,
            )
