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

-- Documentos / PDFs por proyecto. Se llena via Playwright (scraper_ec.playwright_detail)
-- abriendo el modal "find_in_page" de cada proyecto en la SPA Ppless v2 y capturando
-- las URLs de los blobs PDF que el frontend muestra como "attach_file".
CREATE TABLE IF NOT EXISTS documentos (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  n_tramite     TEXT NOT NULL,
  fase          TEXT,                  -- "PROYECTO PRESENTADO", "INFORME NO VINCULANTE UTL", etc.
  descripcion   TEXT,
  url           TEXT NOT NULL,
  orden         INTEGER NOT NULL DEFAULT 0,
  captured_at   TEXT NOT NULL,
  FOREIGN KEY (n_tramite) REFERENCES proyectos(n_tramite)
);
CREATE INDEX IF NOT EXISTS idx_docs_tramite ON documentos(n_tramite);
CREATE UNIQUE INDEX IF NOT EXISTS uq_docs_tramite_url ON documentos(n_tramite, url);

-- Unificaciones de proyectos de ley (Asamblea Nacional EC).
-- Cuando varios PLs sobre la misma materia se unifican para tratamiento
-- conjunto, los marcamos como miembros de un mismo "grupo". Un PL puede
-- estar en 0 o 1 grupo (FK NULL = no unificado).
--
-- Fuente:
--   - Manual via CLI (marcar-unificacion) mientras no scrapeamos el portal
--   - Futuro: Playwright en el detalle del PL en Ppless v2
CREATE TABLE IF NOT EXISTS unificacion_grupos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre          TEXT,                          -- "Reformas a Inquilinato", etc.
  descripcion     TEXT,
  n_tramite_principal TEXT,                      -- el "lead" del grupo (opcional)
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  source          TEXT NOT NULL DEFAULT 'manual' -- manual | portal | inferido
);

CREATE TABLE IF NOT EXISTS unificacion_pl (
  grupo_id        INTEGER NOT NULL,
  n_tramite       TEXT NOT NULL,
  agregado_at     TEXT NOT NULL,
  PRIMARY KEY (grupo_id, n_tramite),
  FOREIGN KEY (grupo_id) REFERENCES unificacion_grupos(id) ON DELETE CASCADE,
  FOREIGN KEY (n_tramite) REFERENCES proyectos(n_tramite)
);
CREATE INDEX IF NOT EXISTS idx_unif_pl_tramite ON unificacion_pl(n_tramite);
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

    # ---------- unificaciones ----------
    def crear_grupo_unificacion(
        self,
        n_tramites: list[str],
        nombre: str | None = None,
        descripcion: str | None = None,
        n_tramite_principal: str | None = None,
        source: str = "manual",
    ) -> int:
        """Crea un grupo de unificacion con N proyectos. Si alguno ya
        pertenece a otro grupo, se lo saca de el primero.

        Returns: grupo_id (INT) creado.
        """
        if not n_tramites:
            raise ValueError("Se requiere al menos 1 n_tramite")
        n_tramites = list(dict.fromkeys(n_tramites))  # dedupe preservando orden
        if n_tramite_principal and n_tramite_principal not in n_tramites:
            n_tramites = [n_tramite_principal] + n_tramites
        now = now_iso()
        with self.tx() as c:
            cur = c.execute(
                """INSERT INTO unificacion_grupos
                   (nombre, descripcion, n_tramite_principal, created_at,
                    updated_at, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (nombre, descripcion, n_tramite_principal or n_tramites[0],
                 now, now, source),
            )
            grupo_id = cur.lastrowid
            for n in n_tramites:
                # Si el PL ya esta en otro grupo, removerlo
                c.execute("DELETE FROM unificacion_pl WHERE n_tramite = ?", (n,))
                c.execute(
                    """INSERT INTO unificacion_pl (grupo_id, n_tramite, agregado_at)
                       VALUES (?, ?, ?)""",
                    (grupo_id, n, now),
                )
        return grupo_id

    def listar_grupos_unificacion(self) -> list[dict]:
        """Devuelve todos los grupos con sus miembros y conteo."""
        rows = self.conn.execute(
            """SELECT g.id, g.nombre, g.descripcion, g.n_tramite_principal,
                      g.source, g.created_at,
                      COUNT(up.n_tramite) AS n_pls,
                      GROUP_CONCAT(up.n_tramite, ',') AS miembros
               FROM unificacion_grupos g
               LEFT JOIN unificacion_pl up ON up.grupo_id = g.id
               GROUP BY g.id
               ORDER BY n_pls DESC, g.id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def borrar_grupo_unificacion(self, grupo_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM unificacion_grupos WHERE id = ?", (grupo_id,))
            # CASCADE deberia borrar unificacion_pl, pero por si acaso:
            c.execute("DELETE FROM unificacion_pl WHERE grupo_id = ?", (grupo_id,))

    def get_unificacion_de(self, n_tramite: str) -> dict | None:
        """Devuelve el grupo (con miembros) al que pertenece un PL, o None."""
        r = self.conn.execute(
            """SELECT g.id, g.nombre, g.descripcion, g.n_tramite_principal,
                      GROUP_CONCAT(up2.n_tramite, ',') AS miembros
               FROM unificacion_pl up
               JOIN unificacion_grupos g ON g.id = up.grupo_id
               JOIN unificacion_pl up2 ON up2.grupo_id = up.grupo_id
               WHERE up.n_tramite = ?
               GROUP BY g.id""",
            (n_tramite,),
        ).fetchone()
        return dict(r) if r else None

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

    # ---------- documentos (PDFs capturados via Playwright) ----------
    def replace_documentos(self, n_tramite: str, docs: list[dict]) -> int:
        """Reemplaza todos los documentos asociados al proyecto.

        Args:
            n_tramite: identificador del proyecto
            docs: lista de {fase, descripcion, url} (orden = posición en la lista)
        Returns:
            Cantidad de documentos persistidos.
        """
        now = now_iso()
        with self.tx() as c:
            c.execute("DELETE FROM documentos WHERE n_tramite = ?", (n_tramite,))
            for i, d in enumerate(docs):
                url = d.get("url")
                if not url:
                    continue
                c.execute(
                    "INSERT OR IGNORE INTO documentos "
                    "(n_tramite, fase, descripcion, url, orden, captured_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (n_tramite, d.get("fase"), d.get("descripcion"), url, i, now),
                )
        return len(docs)

    def get_url_principal(self, n_tramite: str) -> str | None:
        """Devuelve la URL del PDF principal (primer documento por orden)."""
        r = self.conn.execute(
            "SELECT url FROM documentos WHERE n_tramite = ? ORDER BY orden ASC LIMIT 1",
            (n_tramite,),
        ).fetchone()
        return r["url"] if r else None
