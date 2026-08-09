"""Schema + wrapper SQLite para noticias en proyectos.db."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS noticias_fuentes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  categoria       TEXT NOT NULL,         -- "Coyuntura Politica" / "Institucion" / "Temas Salud" / etc.
  pais            TEXT NOT NULL,         -- "PE" / "EC"
  nombre          TEXT NOT NULL,
  url             TEXT,                  -- URL principal del sitio (para link)
  rss_url         TEXT,                  -- URL del feed RSS si esta disponible
  tipo            TEXT NOT NULL DEFAULT 'manual', -- rss | html | api | twitter | manual
  activa          INTEGER NOT NULL DEFAULT 1,
  notas           TEXT,
  created_at      TEXT NOT NULL,
  UNIQUE (pais, nombre)
);

CREATE TABLE IF NOT EXISTS noticias (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  fuente_id       INTEGER NOT NULL,
  url             TEXT UNIQUE NOT NULL,
  titulo          TEXT NOT NULL,
  resumen         TEXT,
  fecha_pub       TEXT,                  -- ISO con timezone si esta
  autor           TEXT,
  tags            TEXT,                  -- pipe-separated
  first_seen_at   TEXT NOT NULL,
  last_seen_at    TEXT NOT NULL,
  FOREIGN KEY (fuente_id) REFERENCES noticias_fuentes(id)
);
CREATE INDEX IF NOT EXISTS idx_noticias_fuente ON noticias(fuente_id);
CREATE INDEX IF NOT EXISTS idx_noticias_fecha ON noticias(fecha_pub DESC);

CREATE TABLE IF NOT EXISTS noticias_sync_runs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  fuentes_visitadas INTEGER DEFAULT 0,
  noticias_nuevas   INTEGER DEFAULT 0,
  noticias_actualizadas INTEGER DEFAULT 0,
  errores         INTEGER DEFAULT 0,
  mensaje         TEXT
);

-- Feedback humano sobre relevancia/clasificación de una noticia.
-- Base para retraining futuro del clasificador.
CREATE TABLE IF NOT EXISTS noticias_feedback (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  noticia_id      INTEGER NOT NULL,
  action          TEXT NOT NULL,           -- 'descartar' | 'confirmar' | 'reclasificar'
  tema_correcto   TEXT,                    -- solo si action='reclasificar'
  created_at      TEXT NOT NULL,
  FOREIGN KEY (noticia_id) REFERENCES noticias(id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_noticia ON noticias_feedback(noticia_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


import re as _re

# Frases de RRSS sin contenido informativo. Match case-insensitive contra
# el titulo entero (no substring): filtra saludos, agradecimientos, RT
# huecos, "hola amigos", etc.
_BASURA_PATRONES = _re.compile(
    r"^\s*(?:"
    r"buen(?:os|as)\s+(?:d[ií]as|tardes|noches)"
    r"|feliz\s+(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|d[ií]a)"
    r"|gracias\s+por\s+(?:seguirnos|estar)"
    r"|s[ií]guenos"
    r"|comparte|comparti|comparta"
    r"|rt\b|retweet"
    r"|hola\s+(?:amigos|a\s+todos)"
    r"|entrevista\s+en\s+vivo"
    r")\b",
    _re.IGNORECASE,
)


_KW_NORMA_CORTA = _re.compile(
    r"\b(?:DS|DU|DL|RM|RS|RD|Ley|Decreto|Resoluci[oó]n|Ordenanza)\b",
    _re.I,
)


def _es_basura(titulo: str | None, resumen: str | None = None) -> bool:
    """True si la 'noticia' es probablemente ruido (tweet vacio, saludo, etc.)."""
    t = (titulo or "").strip()
    tiene_kw_norma = bool(_KW_NORMA_CORTA.search(t))
    # Titulos muy cortos son casi siempre basura, EXCEPTO si mencionan una norma.
    if len(t) < 20 and not tiene_kw_norma:
        return True
    # Sin letras alfabéticas suficientes (solo emojis / hashtags / URLs),
    # y sin ser referencia a una norma.
    if not tiene_kw_norma and not _re.search(r"[a-záéíóúñ]{4,}", t, _re.I):
        return True
    # Frases genericas de RRSS
    if _BASURA_PATRONES.match(t):
        return True
    return False


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

    # ---------- fuentes ----------
    def upsert_fuente(self, row: dict) -> int:
        """Insert si no existe (key: pais + nombre), update si cambio.
        Devuelve fuente_id."""
        now = now_iso()
        existing = self.conn.execute(
            "SELECT id FROM noticias_fuentes WHERE pais=? AND nombre=?",
            (row["pais"], row["nombre"]),
        ).fetchone()
        with self.tx() as c:
            if existing:
                c.execute(
                    """UPDATE noticias_fuentes SET
                       categoria=?, url=?, rss_url=?, tipo=?, activa=?, notas=?
                       WHERE id=?""",
                    (row["categoria"], row.get("url"), row.get("rss_url"),
                     row.get("tipo", "manual"), row.get("activa", 1),
                     row.get("notas"), existing["id"]),
                )
                return existing["id"]
            cur = c.execute(
                """INSERT INTO noticias_fuentes
                   (categoria, pais, nombre, url, rss_url, tipo, activa, notas, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (row["categoria"], row["pais"], row["nombre"], row.get("url"),
                 row.get("rss_url"), row.get("tipo", "manual"),
                 row.get("activa", 1), row.get("notas"), now),
            )
            return cur.lastrowid

    def list_fuentes(self, pais: str | None = None,
                      categoria: str | None = None,
                      solo_activas: bool = True,
                      solo_scrapeables: bool = False) -> list[dict]:
        sql = "SELECT * FROM noticias_fuentes WHERE 1=1"
        params: list = []
        if pais:
            sql += " AND pais=?"; params.append(pais)
        if categoria:
            sql += " AND categoria=?"; params.append(categoria)
        if solo_activas:
            sql += " AND activa=1"
        if solo_scrapeables:
            sql += " AND tipo IN ('rss','html','api','gobpe')"
        sql += " ORDER BY categoria, nombre"
        return [dict(r) for r in self.conn.execute(sql, params)]

    # ---------- noticias ----------
    def upsert_noticia(self, fuente_id: int, row: dict) -> tuple[bool, bool]:
        """Insert nueva (key: url), update si cambio. Devuelve (is_new, changed).

        Aplica filtros de basura antes de persistir: descarta items con
        titulos cortos, solo emojis/hashtags, o frases genericas de RRSS.
        """
        if _es_basura(row.get("titulo"), row.get("resumen")):
            return False, False
        url = row["url"]
        now = now_iso()
        existing = self.conn.execute(
            "SELECT titulo, resumen, fecha_pub FROM noticias WHERE url=?",
            (url,),
        ).fetchone()
        if existing is None:
            with self.tx() as c:
                c.execute(
                    """INSERT INTO noticias
                       (fuente_id, url, titulo, resumen, fecha_pub, autor,
                        tags, first_seen_at, last_seen_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (fuente_id, url, row["titulo"], row.get("resumen"),
                     row.get("fecha_pub"), row.get("autor"),
                     row.get("tags"), now, now),
                )
            return True, True
        # Detectar cambios
        changed = (
            (row.get("titulo") or "") != (existing["titulo"] or "")
            or (row.get("resumen") or "") != (existing["resumen"] or "")
            or (row.get("fecha_pub") or "") != (existing["fecha_pub"] or "")
        )
        with self.tx() as c:
            if changed:
                c.execute(
                    """UPDATE noticias SET titulo=?, resumen=?, fecha_pub=?,
                       last_seen_at=? WHERE url=?""",
                    (row["titulo"], row.get("resumen"), row.get("fecha_pub"),
                     now, url),
                )
            else:
                c.execute("UPDATE noticias SET last_seen_at=? WHERE url=?",
                          (now, url))
        return False, changed

    def count_noticias(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM noticias").fetchone()[0]

    def purge_noticias_antiguas(self, dias: int) -> int:
        """Borra noticias con fecha_pub/first_seen_at anteriores a 'dias' atras.
        Devuelve cantidad eliminada. Mantiene la DB liviana ya que la UI solo
        muestra ventanas cortas (default: solo hoy)."""
        with self.tx() as c:
            cur = c.execute(
                """DELETE FROM noticias
                   WHERE date(COALESCE(fecha_pub, first_seen_at))
                         < date('now', ?)""",
                (f"-{int(dias)} days",),
            )
            return cur.rowcount or 0

    def count_fuentes(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM noticias_fuentes WHERE activa=1"
        ).fetchone()[0]

    # ---------- sync runs ----------
    def start_sync_run(self) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO noticias_sync_runs (started_at) VALUES (?)",
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
                f"UPDATE noticias_sync_runs SET {', '.join(cols)} WHERE id=?",
                vals,
            )
