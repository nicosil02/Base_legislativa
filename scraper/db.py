"""Capa de almacenamiento SQLite."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS comisiones (
  comision_id   INTEGER PRIMARY KEY,
  nombre        TEXT NOT NULL,
  abreviatura   TEXT
);

CREATE TABLE IF NOT EXISTS proyectos (
  per_par_id        INTEGER NOT NULL,
  pley_num          INTEGER NOT NULL,
  pley_id           INTEGER,
  proyecto_ley      TEXT NOT NULL,
  titulo            TEXT NOT NULL,
  sumilla           TEXT,
  estado            TEXT NOT NULL,
  estado_id         INTEGER,
  proponente        TEXT,
  grupo_parlamentario TEXT,
  legislatura       TEXT,
  autores_raw       TEXT,
  fec_presentacion  TEXT NOT NULL,
  url_portal        TEXT NOT NULL,
  url_pdf           TEXT,
  observaciones     TEXT,
  first_seen_at     TEXT NOT NULL,
  last_seen_at      TEXT NOT NULL,
  last_changed_at   TEXT NOT NULL,
  detail_fetched_at TEXT,
  PRIMARY KEY (per_par_id, pley_num)
);
CREATE INDEX IF NOT EXISTS idx_proyectos_estado   ON proyectos(estado);
CREATE INDEX IF NOT EXISTS idx_proyectos_fecha    ON proyectos(fec_presentacion);

CREATE TABLE IF NOT EXISTS proyecto_comision (
  per_par_id   INTEGER NOT NULL,
  pley_num     INTEGER NOT NULL,
  comision_id  INTEGER NOT NULL,
  nombre       TEXT NOT NULL,
  PRIMARY KEY (per_par_id, pley_num, comision_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_comision ON proyecto_comision(comision_id);

DROP TABLE IF EXISTS firmantes;

CREATE TABLE IF NOT EXISTS seguimientos (
  seguimiento_pley_id INTEGER PRIMARY KEY,
  per_par_id     INTEGER NOT NULL,
  pley_num       INTEGER NOT NULL,
  fecha          TEXT NOT NULL,
  estado         TEXT,
  comisiones     TEXT,
  detalle        TEXT,
  observacion    TEXT,
  flag_inicial   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_seg_proyecto ON seguimientos(per_par_id, pley_num);

CREATE TABLE IF NOT EXISTS archivos (
  proyecto_archivo_id INTEGER PRIMARY KEY,
  seguimiento_pley_id INTEGER,
  per_par_id     INTEGER NOT NULL,
  pley_num       INTEGER NOT NULL,
  fecha          TEXT,
  nombre_archivo TEXT,
  descripcion    TEXT,
  url            TEXT
);
CREATE INDEX IF NOT EXISTS idx_arch_proyecto ON archivos(per_par_id, pley_num);

CREATE TABLE IF NOT EXISTS temas (
  tema_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS proyecto_tema (
  per_par_id  INTEGER NOT NULL,
  pley_num    INTEGER NOT NULL,
  tema_id     INTEGER NOT NULL REFERENCES temas(tema_id),
  PRIMARY KEY (per_par_id, pley_num, tema_id)
);
CREATE INDEX IF NOT EXISTS idx_pt_tema ON proyecto_tema(tema_id);

CREATE TABLE IF NOT EXISTS sync_runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  proyectos_vistos       INTEGER DEFAULT 0,
  proyectos_nuevos       INTEGER DEFAULT 0,
  proyectos_actualizados INTEGER DEFAULT 0,
  detail_fetches         INTEGER DEFAULT 0,
  errores                INTEGER DEFAULT 0,
  mensaje                TEXT
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
        from scraper.categorias import all_categorias
        with self.tx() as c:
            c.executescript(SCHEMA)
            for nombre in all_categorias():
                c.execute("INSERT OR IGNORE INTO temas (nombre) VALUES (?)", (nombre,))

    def save_temas(self, per_par_id: int, pley_num: int, temas: list[str]) -> None:
        with self.tx() as c:
            c.execute(
                "DELETE FROM proyecto_tema WHERE per_par_id=? AND pley_num=?",
                (per_par_id, pley_num),
            )
            for nombre in temas:
                c.execute(
                    """INSERT OR IGNORE INTO proyecto_tema (per_par_id, pley_num, tema_id)
                       SELECT ?, ?, tema_id FROM temas WHERE nombre = ?""",
                    (per_par_id, pley_num, nombre),
                )

    def classify_and_save(self, per_par_id: int, pley_num: int,
                          titulo: str | None, sumilla: str | None) -> list[str]:
        from scraper.categorias import classify
        temas = classify(titulo, sumilla)
        self.save_temas(per_par_id, pley_num, temas)
        return temas

    # ---------- comisiones ----------
    def upsert_comisiones(self, rows: Iterable[dict]) -> int:
        n = 0
        with self.tx() as c:
            for r in rows:
                c.execute(
                    "INSERT INTO comisiones (comision_id, nombre, abreviatura) VALUES (?,?,?) "
                    "ON CONFLICT(comision_id) DO UPDATE SET nombre=excluded.nombre, abreviatura=excluded.abreviatura",
                    (r["comisionId"], r["nombreComision"], r.get("nomAbrComision")),
                )
                n += 1
        return n

    def count_comisiones(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM comisiones").fetchone()[0]

    # ---------- proyectos: estado conocido ----------
    def get_known(self, per_par_id: int, pley_num: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM proyectos WHERE per_par_id=? AND pley_num=?",
            (per_par_id, pley_num),
        ).fetchone()

    # ---------- upsert: lista (sin detalle) ----------
    def upsert_from_lista(self, row: dict, now: str) -> tuple[bool, bool]:
        """Inserta o actualiza desde la fila del listado.

        Returns (is_new, estado_changed). estado_changed indica si vale la
        pena llamar al detalle para refrescar comisiones/seguimientos.
        """
        per_par_id = row["perParId"]
        pley_num = row["pleyNum"]
        existing = self.get_known(per_par_id, pley_num)
        portal = f"https://wb2server.congreso.gob.pe/spley-portal/#/expediente/{per_par_id}/{pley_num}"
        if existing is None:
            with self.tx() as c:
                c.execute(
                    """
                    INSERT INTO proyectos
                      (per_par_id, pley_num, proyecto_ley, titulo, estado, proponente,
                       autores_raw, fec_presentacion, url_portal,
                       first_seen_at, last_seen_at, last_changed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        per_par_id, pley_num,
                        row.get("proyectoLey"),
                        row.get("titulo"),
                        row.get("desEstado"),
                        row.get("desProponente"),
                        row.get("autores"),
                        row.get("fecPresentacion"),
                        portal, now, now, now,
                    ),
                )
            # clasificación inicial sólo con título; se refina luego con sumilla en detalle
            self.classify_and_save(per_par_id, pley_num, row.get("titulo"), None)
            return True, True

        nuevo_estado = row.get("desEstado")
        estado_changed = (existing["estado"] != nuevo_estado)
        autores_changed = (existing["autores_raw"] != row.get("autores"))
        titulo_changed = (existing["titulo"] != row.get("titulo"))
        any_change = estado_changed or autores_changed or titulo_changed
        with self.tx() as c:
            c.execute(
                """
                UPDATE proyectos SET
                  proyecto_ley=?, titulo=?, estado=?, proponente=?, autores_raw=?,
                  fec_presentacion=?, last_seen_at=?,
                  last_changed_at=CASE WHEN ? THEN ? ELSE last_changed_at END
                WHERE per_par_id=? AND pley_num=?
                """,
                (
                    row.get("proyectoLey"),
                    row.get("titulo"),
                    nuevo_estado,
                    row.get("desProponente"),
                    row.get("autores"),
                    row.get("fecPresentacion"),
                    now,
                    1 if any_change else 0, now,
                    per_par_id, pley_num,
                ),
            )
        return False, estado_changed

    # ---------- upsert: detalle (expediente) ----------
    def upsert_detalle(self, per_par_id: int, pley_num: int, data: dict, now: str) -> None:
        gen = data.get("general") or {}
        comisiones = data.get("comisiones") or []
        seguimientos = data.get("seguimientos") or []

        # primer archivo encontrado en seguimientos = PDF principal
        url_pdf = None
        from scraper.api import pdf_url
        for s in seguimientos:
            for a in (s.get("archivos") or []):
                aid = a.get("proyectoArchivoId")
                if aid:
                    url_pdf = pdf_url(aid)
                    break
            if url_pdf:
                break

        with self.tx() as c:
            c.execute(
                """
                UPDATE proyectos SET
                  pley_id=?, sumilla=?, estado=?, estado_id=?, proponente=?,
                  grupo_parlamentario=?, legislatura=?, observaciones=?,
                  url_pdf=COALESCE(?, url_pdf), detail_fetched_at=?, last_seen_at=?
                WHERE per_par_id=? AND pley_num=?
                """,
                (
                    gen.get("pleyId"),
                    gen.get("sumilla"),
                    gen.get("desEstado"),
                    gen.get("estadoId"),
                    gen.get("desProponente"),
                    gen.get("desGpar"),
                    gen.get("desLegis"),
                    gen.get("observaciones"),
                    url_pdf, now, now,
                    per_par_id, pley_num,
                ),
            )

            # comisiones del proyecto (replace-all)
            c.execute("DELETE FROM proyecto_comision WHERE per_par_id=? AND pley_num=?", (per_par_id, pley_num))
            for com in comisiones:
                c.execute(
                    "INSERT INTO proyecto_comision (per_par_id, pley_num, comision_id, nombre) VALUES (?,?,?,?)",
                    (per_par_id, pley_num, com.get("comisionId"), com.get("nombre")),
                )

            # seguimientos (insert si nuevos)
            for s in seguimientos:
                sid = s.get("seguimientoPleyId")
                if sid is None:
                    continue
                c.execute(
                    """INSERT OR REPLACE INTO seguimientos
                       (seguimiento_pley_id, per_par_id, pley_num, fecha, estado,
                        comisiones, detalle, observacion, flag_inicial)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        sid, per_par_id, pley_num,
                        s.get("fecha"),
                        s.get("desEstado"),
                        s.get("desComisiones"),
                        s.get("detalle"),
                        s.get("observacion"),
                        1 if s.get("flagInicial") else 0,
                    ),
                )
                for a in (s.get("archivos") or []):
                    aid = a.get("proyectoArchivoId")
                    if aid is None:
                        continue
                    c.execute(
                        """INSERT OR REPLACE INTO archivos
                           (proyecto_archivo_id, seguimiento_pley_id, per_par_id, pley_num,
                            fecha, nombre_archivo, descripcion, url)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            aid, sid, per_par_id, pley_num,
                            a.get("fecha"),
                            a.get("nombreArchivo"),
                            a.get("descripcion"),
                            pdf_url(aid),
                        ),
                    )

            # last_changed_at = fecha del seguimiento más reciente, si la hay
            if seguimientos:
                fechas = [s.get("fecha") for s in seguimientos if s.get("fecha")]
                if fechas:
                    c.execute(
                        "UPDATE proyectos SET last_changed_at=? WHERE per_par_id=? AND pley_num=?",
                        (max(fechas), per_par_id, pley_num),
                    )

        # Clasificar por temas usando título + sumilla (fuera de la transacción anterior,
        # save_temas abre la suya propia).
        self.classify_and_save(
            per_par_id, pley_num,
            gen.get("titulo"),
            gen.get("sumilla"),
        )

    # ---------- sync runs ----------
    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO sync_runs (started_at) VALUES (?)", (now_iso(),)
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, vistos: int, nuevos: int, actualizados: int,
                   detail_fetches: int, errores: int, mensaje: str | None = None) -> None:
        with self.tx() as c:
            c.execute(
                """UPDATE sync_runs SET finished_at=?, proyectos_vistos=?, proyectos_nuevos=?,
                          proyectos_actualizados=?, detail_fetches=?, errores=?, mensaje=?
                   WHERE id=?""",
                (now_iso(), vistos, nuevos, actualizados, detail_fetches, errores, mensaje, run_id),
            )
