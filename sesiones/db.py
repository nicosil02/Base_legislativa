"""Capa de almacenamiento SQLite para sesiones de comisiones.

Comparte el archivo `proyectos.db` con el scraper PE para que los JOINs entre
sesiones <-> PLs sean SQL nativo. Las tablas viven con prefijo `sesion_` /
`sesiones_` para no chocar con las del scraper PE.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
-- Una fila por sesion convocada / realizada de una comision.
CREATE TABLE IF NOT EXISTS sesiones (
  id_sesion           INTEGER PRIMARY KEY,
  id_periodo_leg      INTEGER,
  id_comision_per_leg INTEGER,
  comision_id         INTEGER,
  nombre_comision     TEXT,
  tipo_comision       TEXT,
  nombre_sesion       TEXT,
  fecha               TEXT NOT NULL,          -- ISO YYYY-MM-DD
  hora_inicio         TEXT,
  hora_fin            TEXT,
  estado              TEXT,                   -- 'Convocada', 'Realizada', etc
  estado_id           INTEGER,
  modalidad           INTEGER,
  flag_conjunta       INTEGER DEFAULT 0,
  flag_continuacion   INTEGER DEFAULT 0,
  flag_descentralizada INTEGER DEFAULT 0,
  link_teams          TEXT,
  link_video          TEXT,
  id_alfresco_acta    TEXT,                   -- UUID 36 chars del PDF de acta
  id_alfresco_agenda  TEXT,                   -- UUID 36 chars del PDF de agenda documentada
  id_alfresco_asist   TEXT,                   -- UUID 36 chars del PDF de asistencia
  agenda_estado       INTEGER,
  first_seen_at       TEXT NOT NULL,
  last_seen_at        TEXT NOT NULL,
  last_changed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sesiones_fecha ON sesiones(fecha);
CREATE INDEX IF NOT EXISTS idx_sesiones_comision ON sesiones(comision_id);
CREATE INDEX IF NOT EXISTS idx_sesiones_estado ON sesiones(estado);

-- Cada item del orden del dia de una sesion (HTML rich).
CREATE TABLE IF NOT EXISTS sesion_agenda_punto (
  id_orden_dia        INTEGER PRIMARY KEY,    -- idAgendaOrdenDia del API
  id_sesion           INTEGER NOT NULL,
  orden               INTEGER NOT NULL DEFAULT 0,
  descripcion_html    TEXT,                   -- HTML crudo
  descripcion_texto   TEXT,                   -- HTML strippeado para busqueda
  FOREIGN KEY (id_sesion) REFERENCES sesiones(id_sesion)
);
CREATE INDEX IF NOT EXISTS idx_punto_sesion ON sesion_agenda_punto(id_sesion);

-- M:N entre sesiones y proyectos de ley referenciados en la agenda.
-- Extraidos del HTML via regex (ej. "Proyecto de Ley 14500/2025-CR").
CREATE TABLE IF NOT EXISTS sesion_pl_referenciado (
  id_sesion           INTEGER NOT NULL,
  pley_num            INTEGER NOT NULL,
  per_par_id          INTEGER NOT NULL DEFAULT 2021,
  proyecto_ley_raw    TEXT,                   -- como aparece literal en agenda (ej. "14500/2025-CR")
  contexto            TEXT,                   -- snippet de 120 chars alrededor de la mencion
  id_orden_dia        INTEGER,                -- en que punto del orden del dia aparecio
  PRIMARY KEY (id_sesion, pley_num),
  FOREIGN KEY (id_sesion) REFERENCES sesiones(id_sesion)
);
CREATE INDEX IF NOT EXISTS idx_pl_ref_pley ON sesion_pl_referenciado(pley_num);
CREATE INDEX IF NOT EXISTS idx_pl_ref_sesion ON sesion_pl_referenciado(id_sesion);

-- Bitacora de syncs.
CREATE TABLE IF NOT EXISTS sesiones_sync_runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  sesiones_vistas       INTEGER DEFAULT 0,
  sesiones_nuevas       INTEGER DEFAULT 0,
  sesiones_actualizadas INTEGER DEFAULT 0,
  detail_fetches        INTEGER DEFAULT 0,
  errores               INTEGER DEFAULT 0,
  mensaje               TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_fecha_ddmmyyyy(s: str | None) -> str | None:
    """Convierte 'DD/MM/YYYY' o 'YYYY-MM-DD' a ISO 'YYYY-MM-DD'. None si no se puede."""
    if not s:
        return None
    s = s.strip()
    if len(s) == 10 and s[4] == "-":
        return s
    if len(s) == 10 and s[2] == "/":
        d, m, y = s.split("/")
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return None


class Database:
    """Wrapper fino sobre sqlite3 enfocado a las tablas `sesion_*` y `sesiones`.
    Comparte archivo con scraper/db.py pero opera sobre tablas independientes."""

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

    # ---------- upsert: lista de sesiones ----------
    def upsert_from_lista(self, row: dict, comision_id_map: dict[str, int],
                          now: str) -> tuple[bool, bool]:
        """Inserta o actualiza desde la fila del listado /sesiones/busqueda.

        Returns (is_new, estado_changed). estado_changed indica si vale la pena
        llamar al detalle (porque cambio el estado o es nueva).
        """
        id_sesion = row["idSesion"]
        fecha_iso = _parse_fecha_ddmmyyyy(row.get("fecha"))
        if fecha_iso is None:
            raise ValueError(f"sesion {id_sesion}: fecha invalida {row.get('fecha')!r}")

        nombre_comision = row.get("nombreComision") or ""
        comision_id = comision_id_map.get(nombre_comision)

        existing = self.conn.execute(
            "SELECT estado, fecha FROM sesiones WHERE id_sesion=?", (id_sesion,)
        ).fetchone()

        nuevo_estado = row.get("estado")
        if existing is None:
            with self.tx() as c:
                c.execute(
                    """INSERT INTO sesiones
                       (id_sesion, comision_id, nombre_comision, tipo_comision,
                        nombre_sesion, fecha, hora_inicio, hora_fin, estado,
                        flag_conjunta, flag_continuacion, flag_descentralizada,
                        first_seen_at, last_seen_at, last_changed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        id_sesion, comision_id, nombre_comision,
                        row.get("tipoComision"),
                        row.get("nombreSesion"),
                        fecha_iso,
                        row.get("horaInicio"),
                        row.get("horaFin"),
                        nuevo_estado,
                        1 if row.get("flagConjunta") else 0,
                        1 if row.get("flagContinuacion") else 0,
                        1 if row.get("flagDescentralizado") else 0,
                        now, now, now,
                    ),
                )
            return True, True

        estado_changed = (existing["estado"] != nuevo_estado)
        with self.tx() as c:
            c.execute(
                """UPDATE sesiones SET
                     nombre_comision=?, tipo_comision=?, nombre_sesion=?,
                     hora_inicio=?, hora_fin=?, estado=?,
                     flag_conjunta=?, flag_continuacion=?, flag_descentralizada=?,
                     last_seen_at=?,
                     last_changed_at=CASE WHEN ? THEN ? ELSE last_changed_at END
                   WHERE id_sesion=?""",
                (
                    nombre_comision, row.get("tipoComision"),
                    row.get("nombreSesion"),
                    row.get("horaInicio"), row.get("horaFin"),
                    nuevo_estado,
                    1 if row.get("flagConjunta") else 0,
                    1 if row.get("flagContinuacion") else 0,
                    1 if row.get("flagDescentralizado") else 0,
                    now,
                    1 if estado_changed else 0, now,
                    id_sesion,
                ),
            )
        return False, estado_changed

    # ---------- upsert: detalle (agenda + alfresco IDs) ----------
    def upsert_detalle(self, data: dict, pls_extraidos_por_punto: dict[int, list[dict]],
                        now: str) -> None:
        """Persiste el detalle: campos extra de la sesion + ordenes del dia +
        referencias a PLs (M:N).

        pls_extraidos_por_punto: dict {id_orden_dia: [{pley_num, raw, contexto}, ...]}
        """
        id_sesion = data["idSesion"]
        agenda = data.get("agenda") or {}

        # Update campos de detalle
        with self.tx() as c:
            c.execute(
                """UPDATE sesiones SET
                     id_periodo_leg=?, id_comision_per_leg=?, modalidad=?,
                     estado_id=?, link_teams=?, link_video=?,
                     id_alfresco_acta=?, id_alfresco_agenda=?, id_alfresco_asist=?,
                     agenda_estado=?, last_seen_at=?
                   WHERE id_sesion=?""",
                (
                    data.get("idPeriodoLeg"),
                    data.get("idComisionPerLeg"),
                    data.get("modalidad"),
                    data.get("estado"),
                    data.get("link"),
                    agenda.get("video"),
                    agenda.get("idAlfrescoActaPdf") or None,
                    agenda.get("idAlfrescoAgendaDocumentada") or None,
                    agenda.get("idAlfrescoAsistencia") or None,
                    agenda.get("estado"),
                    now,
                    id_sesion,
                ),
            )
            # Replace de ordenes del dia (es chico, hacemos delete+insert)
            c.execute("DELETE FROM sesion_agenda_punto WHERE id_sesion=?", (id_sesion,))
            ordenes = agenda.get("ordenesDia") or []
            for i, p in enumerate(ordenes):
                id_orden = p.get("idAgendaOrdenDia")
                if id_orden is None:
                    continue
                c.execute(
                    """INSERT OR REPLACE INTO sesion_agenda_punto
                       (id_orden_dia, id_sesion, orden, descripcion_html, descripcion_texto)
                       VALUES (?,?,?,?,?)""",
                    (id_orden, id_sesion, i,
                     p.get("descripcion"),
                     # descripcion_texto se rellena con el parser
                     p.get("_texto_plano")),
                )

            # Replace de PLs referenciados
            c.execute("DELETE FROM sesion_pl_referenciado WHERE id_sesion=?", (id_sesion,))
            for id_orden, pls in pls_extraidos_por_punto.items():
                for pl in pls:
                    try:
                        c.execute(
                            """INSERT OR IGNORE INTO sesion_pl_referenciado
                               (id_sesion, pley_num, per_par_id, proyecto_ley_raw,
                                contexto, id_orden_dia)
                               VALUES (?,?,?,?,?,?)""",
                            (id_sesion, pl["pley_num"],
                             pl.get("per_par_id", 2021),
                             pl.get("raw"),
                             pl.get("contexto"),
                             id_orden),
                        )
                    except Exception:
                        # ignorar PLs duplicados / pley_num invalido
                        pass

    # ---------- sync runs ----------
    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO sesiones_sync_runs (started_at) VALUES (?)", (now_iso(),)
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, vistas: int, nuevas: int,
                   actualizadas: int, detail_fetches: int, errores: int,
                   mensaje: str | None = None) -> None:
        with self.tx() as c:
            c.execute(
                """UPDATE sesiones_sync_runs SET finished_at=?, sesiones_vistas=?,
                          sesiones_nuevas=?, sesiones_actualizadas=?,
                          detail_fetches=?, errores=?, mensaje=?
                   WHERE id=?""",
                (now_iso(), vistas, nuevas, actualizadas, detail_fetches, errores,
                 mensaje, run_id),
            )

    def count_sesiones(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0]
