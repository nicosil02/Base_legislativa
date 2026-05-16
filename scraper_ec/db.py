"""Capa de almacenamiento SQLite para Ecuador (Asamblea Nacional).

Schema separado de Perú: identificador es n_tramite (TEXT — puede ser
numérico tipo "480824" o alfanumérico tipo "AN-BCDP-2026-0065-M").

Fuente de datos: CSV export del portal Ppless v2 (proyectosdeley.asambleanacional.gob.ec)
con 9 columnas. No usamos API directo porque devuelve 403 desde fetch externo.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS proyectos (
  n_tramite              TEXT PRIMARY KEY,
  n_documento            TEXT,
  titulo                 TEXT NOT NULL,
  estado                 TEXT NOT NULL,
  comision_asignada      TEXT,
  proponentes_raw        TEXT,
  tipo_proponente        TEXT,
  fec_documento          TEXT,
  fec_presentacion       TEXT NOT NULL,
  fec_calificacion_cal   TEXT,
  periodo                TEXT NOT NULL DEFAULT '2025-2029',
  url_portal             TEXT,
  tema                   TEXT,
  tema_manual            INTEGER NOT NULL DEFAULT 0,
  first_seen_at          TEXT NOT NULL,
  last_seen_at           TEXT NOT NULL,
  last_changed_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proy_ec_estado    ON proyectos(estado);
CREATE INDEX IF NOT EXISTS idx_proy_ec_fecha     ON proyectos(fec_presentacion);
CREATE INDEX IF NOT EXISTS idx_proy_ec_comision  ON proyectos(comision_asignada);
CREATE INDEX IF NOT EXISTS idx_proy_ec_tema      ON proyectos(tema);

CREATE TABLE IF NOT EXISTS proponentes (
  n_tramite     TEXT NOT NULL,
  nombre        TEXT NOT NULL,
  tipo          TEXT,
  orden         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (n_tramite, nombre),
  FOREIGN KEY (n_tramite) REFERENCES proyectos(n_tramite)
);
CREATE INDEX IF NOT EXISTS idx_propon_tramite ON proponentes(n_tramite);
CREATE INDEX IF NOT EXISTS idx_propon_nombre  ON proponentes(nombre);

CREATE TABLE IF NOT EXISTS historial_cambios (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  n_tramite     TEXT NOT NULL,
  changed_at    TEXT NOT NULL,
  campo         TEXT NOT NULL,
  valor_antes   TEXT,
  valor_despues TEXT,
  FOREIGN KEY (n_tramite) REFERENCES proyectos(n_tramite)
);
CREATE INDEX IF NOT EXISTS idx_hist_tramite ON historial_cambios(n_tramite);

CREATE TABLE IF NOT EXISTS sync_runs (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at              TEXT NOT NULL,
  finished_at             TEXT,
  proyectos_vistos        INTEGER DEFAULT 0,
  proyectos_nuevos        INTEGER DEFAULT 0,
  proyectos_actualizados  INTEGER DEFAULT 0,
  errores                 INTEGER DEFAULT 0,
  csv_source              TEXT,
  mensaje                 TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Campos del proyecto que se trackean en historial_cambios cuando cambian
# entre snapshots sucesivos.
TRACKED_FIELDS = ("estado", "comision_asignada", "titulo", "fec_calificacion_cal")


class Database:
    """Wrapper fino sobre sqlite3 para proyectos_ec.db."""

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

    # ---------- proyectos ----------
    def get_known(self, n_tramite: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM proyectos WHERE n_tramite = ?", (n_tramite,)
        ).fetchone()

    def upsert_from_csv_row(self, row: dict, now: str) -> tuple[bool, list[str]]:
        """Inserta o actualiza un proyecto desde una fila del CSV de Ppless.

        Returns:
            (is_new, changed_fields)
            - is_new: True si el proyecto no existía
            - changed_fields: lista de nombres de columna que cambiaron (vacía si nada)
        """
        n_tramite = row["n_tramite"]
        existing = self.get_known(n_tramite)
        if existing is None:
            with self.tx() as c:
                c.execute(
                    """
                    INSERT INTO proyectos
                      (n_tramite, n_documento, titulo, estado, comision_asignada,
                       proponentes_raw, tipo_proponente, fec_documento, fec_presentacion,
                       fec_calificacion_cal, periodo, url_portal,
                       first_seen_at, last_seen_at, last_changed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        n_tramite, row.get("n_documento"), row["titulo"], row["estado"],
                        row.get("comision_asignada"), row.get("proponentes_raw"),
                        row.get("tipo_proponente"), row.get("fec_documento"),
                        row["fec_presentacion"], row.get("fec_calificacion_cal"),
                        row.get("periodo", "2025-2029"), row.get("url_portal"),
                        now, now, now,
                    ),
                )
            # Insertar proponentes individualizados
            self._replace_proponentes(n_tramite, row.get("proponentes_lista") or [])
            return True, ["__new__"]

        # Comparar campos trackeados
        changed: list[str] = []
        for field in TRACKED_FIELDS:
            old = existing[field] if field in existing.keys() else None
            new = row.get(field) if field in row else None
            if (old or None) != (new or None):
                changed.append(field)

        with self.tx() as c:
            c.execute(
                """
                UPDATE proyectos SET
                  n_documento=?, titulo=?, estado=?, comision_asignada=?,
                  proponentes_raw=?, tipo_proponente=?, fec_documento=?,
                  fec_presentacion=?, fec_calificacion_cal=?, url_portal=COALESCE(?, url_portal),
                  last_seen_at=?,
                  last_changed_at=CASE WHEN ? THEN ? ELSE last_changed_at END
                WHERE n_tramite=?
                """,
                (
                    row.get("n_documento"), row["titulo"], row["estado"],
                    row.get("comision_asignada"), row.get("proponentes_raw"),
                    row.get("tipo_proponente"), row.get("fec_documento"),
                    row["fec_presentacion"], row.get("fec_calificacion_cal"),
                    row.get("url_portal"),
                    now,
                    1 if changed else 0, now,
                    n_tramite,
                ),
            )
            # Log de cambios por campo
            for field in changed:
                old = existing[field] if field in existing.keys() else None
                c.execute(
                    """INSERT INTO historial_cambios
                       (n_tramite, changed_at, campo, valor_antes, valor_despues)
                       VALUES (?,?,?,?,?)""",
                    (n_tramite, now, field, str(old or ""), str(row.get(field) or "")),
                )
        # Replace proponentes list (siempre, por si cambió)
        self._replace_proponentes(n_tramite, row.get("proponentes_lista") or [])
        return False, changed

    def _replace_proponentes(self, n_tramite: str, proponentes: list[dict]) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM proponentes WHERE n_tramite = ?", (n_tramite,))
            for i, p in enumerate(proponentes):
                c.execute(
                    "INSERT OR IGNORE INTO proponentes (n_tramite, nombre, tipo, orden) "
                    "VALUES (?,?,?,?)",
                    (n_tramite, p["nombre"], p.get("tipo"), i),
                )

    def set_tema(self, n_tramite: str, tema: str, *, manual: bool) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE proyectos SET tema=?, tema_manual=? WHERE n_tramite=?",
                (tema, 1 if manual else 0, n_tramite),
            )

    def classify_and_save(self, n_tramite: str, titulo: str | None) -> str | None:
        """Clasifica el proyecto via keywords (sin sumilla — el CSV no la incluye).
        Respeta tema_manual=1 (no toca etiquetas a mano)."""
        from scraper_ec.categorias_ec import classify
        row = self.conn.execute(
            "SELECT tema_manual FROM proyectos WHERE n_tramite=?", (n_tramite,)
        ).fetchone()
        if row and row["tema_manual"]:
            return None
        tema = classify(titulo, None)
        self.set_tema(n_tramite, tema, manual=False)
        return tema

    # ---------- sync runs ----------
    def start_run(self, csv_source: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO sync_runs (started_at, csv_source) VALUES (?, ?)",
            (now_iso(), csv_source),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, vistos: int, nuevos: int,
                   actualizados: int, errores: int,
                   mensaje: str | None = None) -> None:
        with self.tx() as c:
            c.execute(
                """UPDATE sync_runs
                   SET finished_at=?, proyectos_vistos=?, proyectos_nuevos=?,
                       proyectos_actualizados=?, errores=?, mensaje=?
                   WHERE id=?""",
                (now_iso(), vistos, nuevos, actualizados, errores, mensaje, run_id),
            )

    def count_proyectos(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM proyectos").fetchone()[0]
