"""Capa de almacenamiento SQLite para sesiones del Pleno del Congreso.

Comparte el archivo `proyectos.db` con scraper/, sesiones/ y la app. Las tablas
usan prefijo `pleno_` para no chocar con las demas. El cruce con PLs usa el
mismo identificador (`pley_num`, INT) que ya estan usando todos los modulos.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
-- Una fila por agenda del Pleno (sesion plenaria del jueves, tipicamente).
CREATE TABLE IF NOT EXISTS pleno_sesiones (
  cod_agenda           INTEGER PRIMARY KEY,
  periodo              TEXT,                    -- "2021-2026"
  ano_legis            TEXT,                    -- "2025"
  legislatura          TEXT,                    -- "Segunda Legislatura Ordinaria 2025 - 2026"
  fecha_sesion         TEXT NOT NULL,           -- ISO YYYY-MM-DD
  fecha_fin_sesion     TEXT,                    -- a veces multi-dia
  titulo               TEXT,                    -- "Sesion del jueves 21 de mayo de 2026"
  presidente           TEXT,
  estado_agenda        INTEGER,
  tipo_agenda          INTEGER,
  fec_publicacion      TEXT,
  url_publicacion      TEXT,
  ind_publicado        INTEGER DEFAULT 1,
  first_seen_at        TEXT NOT NULL,
  last_seen_at         TEXT NOT NULL,
  last_changed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pleno_sesiones_fecha ON pleno_sesiones(fecha_sesion);

-- Cada tema de la agenda (= 1 punto del orden del dia). Puede ser un dictamen,
-- un proyecto de resolucion legislativa, una mocion, etc. Usualmente referencia
-- 1 Proyecto de Ley (parseado al cruce M:N pleno_pl_referenciado).
CREATE TABLE IF NOT EXISTS pleno_tema (
  cod_tema             INTEGER PRIMARY KEY,
  cod_agenda           INTEGER NOT NULL,
  cod_sec              INTEGER,
  des_sec              TEXT,                    -- "Dictamenes" / "Proyectos de Resolucion Legislativa"
  cod_sub_sec          INTEGER,
  des_sub_sec          TEXT,
  num_tema             INTEGER,
  nom_tema_cor         TEXT,                    -- "Proyecto de Ley 594"
  des_url              TEXT,                    -- URL canonica al portal
  des_comisiones       TEXT,                    -- comision dictaminadora ("Cultura y Patrimonio Cultural")
  des_resumen          TEXT,                    -- resumen estructurado
  des_tema_html        TEXT,                    -- HTML rich con tribuna completa
  des_tema_texto       TEXT,                    -- HTML strippeado para fulltext
  cod_est_tema         TEXT,
  nota_estado          TEXT,
  ind_publicado        INTEGER,
  FOREIGN KEY (cod_agenda) REFERENCES pleno_sesiones(cod_agenda)
);
CREATE INDEX IF NOT EXISTS idx_pleno_tema_agenda ON pleno_tema(cod_agenda);

-- M:N entre temas del Pleno y proyectos de ley referenciados. Un tema
-- "Acumulado de los PL 1234 y 5678" genera 2 filas. Permite cruzar con la
-- tabla `proyectos` por pley_num.
CREATE TABLE IF NOT EXISTS pleno_pl_referenciado (
  cod_tema             INTEGER NOT NULL,
  cod_agenda           INTEGER NOT NULL,
  pley_num             INTEGER NOT NULL,
  per_par_id           INTEGER NOT NULL DEFAULT 2021,
  proyecto_ley_raw     TEXT,
  origen               TEXT,                    -- 'url_canonica' | 'regex_texto'
  PRIMARY KEY (cod_tema, pley_num)
);
CREATE INDEX IF NOT EXISTS idx_pleno_pl_ref_pley ON pleno_pl_referenciado(pley_num);
CREATE INDEX IF NOT EXISTS idx_pleno_pl_ref_agenda ON pleno_pl_referenciado(cod_agenda);

CREATE TABLE IF NOT EXISTS pleno_sync_runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  agendas_vistas       INTEGER DEFAULT 0,
  agendas_nuevas       INTEGER DEFAULT 0,
  agendas_actualizadas INTEGER DEFAULT 0,
  detail_fetches       INTEGER DEFAULT 0,
  errores              INTEGER DEFAULT 0,
  mensaje              TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_fecha_iso(s: str | None) -> str | None:
    """Convierte '2026-05-21T00:00:00.000-05:00' -> '2026-05-21'."""
    if not s:
        return None
    s = s.strip()
    if len(s) >= 10:
        cand = s[:10]
        if cand[4] == "-" and cand[7] == "-":
            return cand
    return None


class Database:
    """Wrapper sobre sqlite3 enfocado a las tablas `pleno_*`. Comparte archivo
    con scraper/db.py y sesiones/db.py pero opera sobre tablas independientes."""

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

    # ---------- upsert: lista de agendas ----------
    def upsert_from_lista(self, row: dict, now: str) -> tuple[bool, bool]:
        """Inserta o actualiza desde la fila del listado /visor/publicado.

        Returns (is_new, changed). `changed` indica si vale la pena llamar al
        detalle (porque la agenda es nueva o cambio el titulo/url).
        """
        cod_agenda = row["codAgenda"]
        fecha_iso = _parse_fecha_iso(row.get("fecSesion"))
        if fecha_iso is None:
            raise ValueError(f"agenda {cod_agenda}: fecSesion invalida {row.get('fecSesion')!r}")

        existing = self.conn.execute(
            "SELECT titulo, url_publicacion FROM pleno_sesiones WHERE cod_agenda=?",
            (cod_agenda,),
        ).fetchone()

        titulo = row.get("dTitulo") or ""
        url_pub = row.get("dUrl") or ""

        if existing is None:
            with self.tx() as c:
                c.execute(
                    """INSERT INTO pleno_sesiones
                       (cod_agenda, periodo, ano_legis, legislatura,
                        fecha_sesion, titulo, url_publicacion,
                        first_seen_at, last_seen_at, last_changed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        cod_agenda,
                        row.get("dPeriodo"),
                        row.get("dLegis") and str(row.get("dLegis")).split()[-1],
                        row.get("dLegis"),
                        fecha_iso,
                        titulo,
                        url_pub,
                        now, now, now,
                    ),
                )
            return True, True

        changed = (existing["titulo"] != titulo) or (existing["url_publicacion"] != url_pub)
        with self.tx() as c:
            c.execute(
                """UPDATE pleno_sesiones SET
                     periodo=?, legislatura=?, fecha_sesion=?, titulo=?,
                     url_publicacion=?, last_seen_at=?,
                     last_changed_at=CASE WHEN ? THEN ? ELSE last_changed_at END
                   WHERE cod_agenda=?""",
                (
                    row.get("dPeriodo"),
                    row.get("dLegis"),
                    fecha_iso,
                    titulo,
                    url_pub,
                    now,
                    1 if changed else 0, now,
                    cod_agenda,
                ),
            )
        return False, changed

    # ---------- upsert: detalle (temas + PLs cruzados) ----------
    def upsert_detalle(self, data: dict,
                       temas_con_pls: list[dict],
                       now: str) -> None:
        """Persiste el detalle completo: campos extra de la agenda + temas +
        cruce M:N de PLs.

        `temas_con_pls` es una lista de dicts:
          {tema_row: <dict para INSERT en pleno_tema>,
           pls: [{pley_num, raw, origen}, ...]}
        """
        cod_agenda = data["codAgenda"]
        with self.tx() as c:
            c.execute(
                """UPDATE pleno_sesiones SET
                     ano_legis=?, presidente=?, estado_agenda=?, tipo_agenda=?,
                     fec_publicacion=?, ind_publicado=?, fecha_fin_sesion=?,
                     last_seen_at=?
                   WHERE cod_agenda=?""",
                (
                    data.get("cAnoLegis"),
                    data.get("dPresidente"),
                    data.get("codEstAgenda"),
                    data.get("codTipAgenda"),
                    _parse_fecha_iso(data.get("fecPub")),
                    1 if data.get("indPublicado") else 0,
                    _parse_fecha_iso(data.get("fecFinSesion")),
                    now,
                    cod_agenda,
                ),
            )
            # Replace temas (es chico, delete+insert)
            c.execute("DELETE FROM pleno_pl_referenciado WHERE cod_agenda=?", (cod_agenda,))
            c.execute("DELETE FROM pleno_tema WHERE cod_agenda=?", (cod_agenda,))
            for item in temas_con_pls:
                t = item["tema_row"]
                c.execute(
                    """INSERT OR REPLACE INTO pleno_tema
                       (cod_tema, cod_agenda, cod_sec, des_sec, cod_sub_sec,
                        des_sub_sec, num_tema, nom_tema_cor, des_url,
                        des_comisiones, des_resumen, des_tema_html,
                        des_tema_texto, cod_est_tema, nota_estado, ind_publicado)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        t["cod_tema"], cod_agenda, t.get("cod_sec"),
                        t.get("des_sec"), t.get("cod_sub_sec"), t.get("des_sub_sec"),
                        t.get("num_tema"), t.get("nom_tema_cor"), t.get("des_url"),
                        t.get("des_comisiones"), t.get("des_resumen"),
                        t.get("des_tema_html"), t.get("des_tema_texto"),
                        t.get("cod_est_tema"), t.get("nota_estado"),
                        1 if t.get("ind_publicado") else 0,
                    ),
                )
                for pl in item["pls"]:
                    try:
                        c.execute(
                            """INSERT OR IGNORE INTO pleno_pl_referenciado
                               (cod_tema, cod_agenda, pley_num, per_par_id,
                                proyecto_ley_raw, origen)
                               VALUES (?,?,?,?,?,?)""",
                            (
                                t["cod_tema"], cod_agenda, pl["pley_num"],
                                pl.get("per_par_id", 2021),
                                pl.get("raw"),
                                pl.get("origen"),
                            ),
                        )
                    except Exception:
                        pass

    # ---------- sync runs ----------
    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO pleno_sync_runs (started_at) VALUES (?)", (now_iso(),)
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, vistas: int, nuevas: int,
                   actualizadas: int, detail_fetches: int, errores: int,
                   mensaje: str | None = None) -> None:
        with self.tx() as c:
            c.execute(
                """UPDATE pleno_sync_runs SET finished_at=?, agendas_vistas=?,
                          agendas_nuevas=?, agendas_actualizadas=?,
                          detail_fetches=?, errores=?, mensaje=?
                   WHERE id=?""",
                (now_iso(), vistas, nuevas, actualizadas, detail_fetches, errores,
                 mensaje, run_id),
            )

    def count_agendas(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM pleno_sesiones").fetchone()[0]
