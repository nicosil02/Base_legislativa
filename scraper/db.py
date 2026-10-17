"""Capa de almacenamiento SQLite."""
from __future__ import annotations

import sqlite3
from typing import Iterable

from core.db import Database as _Base, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS comisiones (
  comision_id   INTEGER PRIMARY KEY,
  nombre        TEXT NOT NULL,
  abreviatura   TEXT
);

-- cod_tipo_parl: 'C' Congreso/general, 'D' Diputados, 'S' Senado. Va en la PK
-- porque cada cámara numera desde 1 (D-1 y S-1 son PLs distintos).
CREATE TABLE IF NOT EXISTS proyectos (
  per_par_id        INTEGER NOT NULL,
  cod_tipo_parl     TEXT NOT NULL DEFAULT 'C',
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
  PRIMARY KEY (per_par_id, cod_tipo_parl, pley_num)
);
CREATE INDEX IF NOT EXISTS idx_proyectos_estado   ON proyectos(estado);
CREATE INDEX IF NOT EXISTS idx_proyectos_fecha    ON proyectos(fec_presentacion);

CREATE TABLE IF NOT EXISTS proyecto_comision (
  per_par_id   INTEGER NOT NULL,
  cod_tipo_parl TEXT NOT NULL DEFAULT 'C',
  pley_num     INTEGER NOT NULL,
  comision_id  INTEGER NOT NULL,
  nombre       TEXT NOT NULL,
  PRIMARY KEY (per_par_id, cod_tipo_parl, pley_num, comision_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_comision ON proyecto_comision(comision_id);

DROP TABLE IF EXISTS firmantes;

CREATE TABLE IF NOT EXISTS seguimientos (
  seguimiento_pley_id INTEGER PRIMARY KEY,
  per_par_id     INTEGER NOT NULL,
  cod_tipo_parl  TEXT NOT NULL DEFAULT 'C',
  pley_num       INTEGER NOT NULL,
  fecha          TEXT NOT NULL,
  estado         TEXT,
  comisiones     TEXT,
  detalle        TEXT,
  observacion    TEXT,
  flag_inicial   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_seg_proyecto ON seguimientos(per_par_id, cod_tipo_parl, pley_num);

CREATE TABLE IF NOT EXISTS archivos (
  proyecto_archivo_id INTEGER PRIMARY KEY,
  seguimiento_pley_id INTEGER,
  per_par_id     INTEGER NOT NULL,
  cod_tipo_parl  TEXT NOT NULL DEFAULT 'C',
  pley_num       INTEGER NOT NULL,
  fecha          TEXT,
  nombre_archivo TEXT,
  descripcion    TEXT,
  url            TEXT
);
CREATE INDEX IF NOT EXISTS idx_arch_proyecto ON archivos(per_par_id, cod_tipo_parl, pley_num);

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


class Database(_Base):
    def init_schema(self) -> None:
        from scraper.comisiones_ordinarias import tipo_de
        with self.tx() as c:
            c.executescript(SCHEMA)
            # Migración: proyectos.tema y proyectos.tema_manual.
            cols = {r[1] for r in c.execute("PRAGMA table_info(proyectos)").fetchall()}
            if "tema" not in cols:
                c.execute("ALTER TABLE proyectos ADD COLUMN tema TEXT")
            if "tema_manual" not in cols:
                c.execute("ALTER TABLE proyectos ADD COLUMN tema_manual INTEGER NOT NULL DEFAULT 0")
            # Drop legacy multi-tag.
            c.execute("DROP TABLE IF EXISTS proyecto_tema")
            c.execute("DROP TABLE IF EXISTS temas")
            c.execute("CREATE INDEX IF NOT EXISTS idx_proyectos_tema ON proyectos(tema)")
            # comisiones.tipo: ver scraper/comisiones_ordinarias.py.
            cols_com = {r[1] for r in c.execute("PRAGMA table_info(comisiones)").fetchall()}
            if "tipo" not in cols_com:
                c.execute("ALTER TABLE comisiones ADD COLUMN tipo TEXT NOT NULL DEFAULT 'Especial'")
            # Repoblar el tipo en cada corrida: por comisionId para las cámaras
            # del período bicameral, por nombre para las 24 ordinarias legacy.
            for r in c.execute("SELECT comision_id, nombre FROM comisiones").fetchall():
                c.execute(
                    "UPDATE comisiones SET tipo=? WHERE comision_id=?",
                    (tipo_de(r["comision_id"], r["nombre"]), r["comision_id"]),
                )
            c.execute("CREATE INDEX IF NOT EXISTS idx_comisiones_tipo ON comisiones(tipo)")

    def set_tema(self, per_par_id: int, cod_tipo_parl: str, pley_num: int, tema: str, *, manual: bool) -> None:
        """Asigna un tema al proyecto. Si manual=True marca para que el
        clasificador automático no lo sobrescriba luego."""
        with self.tx() as c:
            c.execute(
                "UPDATE proyectos SET tema=?, tema_manual=? WHERE per_par_id=? AND cod_tipo_parl=? AND pley_num=?",
                (tema, 1 if manual else 0, per_par_id, cod_tipo_parl, pley_num),
            )

    def classify_and_save(self, per_par_id: int, cod_tipo_parl: str, pley_num: int,
                          titulo: str | None, sumilla: str | None) -> str | None:
        """Clasifica el PL sin tocar los tema_manual=1. Primero el modelo ML
        (solo si confianza >= 0.5: mejor "Otros" que una etiqueta dudosa);
        si no hay modelo o no alcanza, las keywords de scraper/categorias."""
        row = self.conn.execute(
            "SELECT tema_manual FROM proyectos WHERE per_par_id=? AND cod_tipo_parl=? AND pley_num=?",
            (per_par_id, cod_tipo_parl, pley_num),
        ).fetchone()
        if row and row["tema_manual"]:
            return None  # respetar la etiqueta manual

        # Intentar ML primero
        tema = None
        try:
            from clasificador.predict import predict_tema
            tema_ml, conf = predict_tema(titulo, sumilla)
            if conf >= 0.5:
                tema = tema_ml
        except Exception:
            # Modelo no entrenado / sklearn no disponible / archivo missing
            pass

        # Fallback al clasificador keywords si ML no aplico
        if tema is None:
            from scraper.categorias import classify
            tema = classify(titulo, sumilla)

        self.set_tema(per_par_id, cod_tipo_parl, pley_num, tema, manual=False)
        return tema

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
    def get_known(self, per_par_id: int, cod_tipo_parl: str, pley_num: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM proyectos WHERE per_par_id=? AND cod_tipo_parl=? AND pley_num=?",
            (per_par_id, cod_tipo_parl, pley_num),
        ).fetchone()

    # ---------- upsert: lista (sin detalle) ----------
    def upsert_from_lista(self, row: dict, now: str) -> tuple[bool, bool]:
        """Inserta o actualiza desde la fila del listado.

        Returns (is_new, estado_changed). estado_changed indica si vale la
        pena llamar al detalle para refrescar comisiones/seguimientos.
        """
        from scraper.api import portal_url

        per_par_id = row["perParId"]
        pley_num = row["pleyNum"]
        # El período legacy no trae codTipoParl -> 'C'.
        cod_tipo_parl = row.get("codTipoParl") or "C"
        existing = self.get_known(per_par_id, cod_tipo_parl, pley_num)
        portal = portal_url(per_par_id, pley_num, cod_tipo_parl)
        if existing is None:
            with self.tx() as c:
                c.execute(
                    """
                    INSERT INTO proyectos
                      (per_par_id, cod_tipo_parl, pley_num, proyecto_ley, titulo, estado, proponente,
                       autores_raw, fec_presentacion, url_portal,
                       first_seen_at, last_seen_at, last_changed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        per_par_id, cod_tipo_parl, pley_num,
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
            self.classify_and_save(per_par_id, cod_tipo_parl, pley_num, row.get("titulo"), None)
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
                WHERE per_par_id=? AND cod_tipo_parl=? AND pley_num=?
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
                    per_par_id, cod_tipo_parl, pley_num,
                ),
            )
        return False, estado_changed

    def _comisiones_desde_seguimientos(self, cod_tipo_parl: str, seguimientos: list[dict]) -> list[dict]:
        """Comisiones sacadas del texto libre `desComisiones` (el período
        bicameral ya no trae el campo `comisiones`), contra el catálogo de la
        cámara del PL. Se busca cada nombre como substring, el más largo
        primero: partir por coma o "y" rompía nombres que los llevan dentro."""
        from scraper.comisiones_ordinarias import TIPOS_POR_CAMARA, normalize

        tipos = TIPOS_POR_CAMARA.get(cod_tipo_parl, ("Ordinaria", "Bicameral"))
        placeholders = ",".join("?" * len(tipos))
        catalogo = sorted(
            (
                (normalize(nombre), cid, nombre)
                for cid, nombre in self.conn.execute(
                    f"SELECT comision_id, nombre FROM comisiones WHERE tipo IN ({placeholders})",
                    tipos,
                ).fetchall()
            ),
            key=lambda t: -len(t[0]),
        )
        if not catalogo:
            return []

        vistos: dict[int, dict] = {}
        for s in seguimientos:
            texto = normalize(s.get("desComisiones"))
            if not texto:
                continue
            for nombre_norm, cid, nombre in catalogo:
                if nombre_norm and nombre_norm in texto:
                    vistos[cid] = {"comisionId": cid, "nombre": nombre}
        return list(vistos.values())

    # ---------- upsert: detalle (expediente) ----------
    def upsert_detalle(self, per_par_id: int, cod_tipo_parl: str, pley_num: int, data: dict, now: str) -> None:
        gen = data.get("general") or {}
        comisiones = data.get("comisiones") or []
        seguimientos = data.get("seguimientos") or []
        if not comisiones:
            comisiones = self._comisiones_desde_seguimientos(cod_tipo_parl, seguimientos)

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
                WHERE per_par_id=? AND cod_tipo_parl=? AND pley_num=?
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
                    per_par_id, cod_tipo_parl, pley_num,
                ),
            )

            # comisiones del proyecto (replace-all)
            c.execute(
                "DELETE FROM proyecto_comision WHERE per_par_id=? AND cod_tipo_parl=? AND pley_num=?",
                (per_par_id, cod_tipo_parl, pley_num),
            )
            for com in comisiones:
                c.execute(
                    "INSERT INTO proyecto_comision (per_par_id, cod_tipo_parl, pley_num, comision_id, nombre) "
                    "VALUES (?,?,?,?,?)",
                    (per_par_id, cod_tipo_parl, pley_num, com.get("comisionId"), com.get("nombre")),
                )

            # seguimientos (insert si nuevos)
            for s in seguimientos:
                sid = s.get("seguimientoPleyId")
                if sid is None:
                    continue
                c.execute(
                    """INSERT OR REPLACE INTO seguimientos
                       (seguimiento_pley_id, per_par_id, cod_tipo_parl, pley_num, fecha, estado,
                        comisiones, detalle, observacion, flag_inicial)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sid, per_par_id, cod_tipo_parl, pley_num,
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
                           (proyecto_archivo_id, seguimiento_pley_id, per_par_id, cod_tipo_parl, pley_num,
                            fecha, nombre_archivo, descripcion, url)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            aid, sid, per_par_id, cod_tipo_parl, pley_num,
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
                        "UPDATE proyectos SET last_changed_at=? WHERE per_par_id=? AND cod_tipo_parl=? AND pley_num=?",
                        (max(fechas), per_par_id, cod_tipo_parl, pley_num),
                    )

        # Fuera de la transacción: set_tema abre la suya.
        self.classify_and_save(
            per_par_id, cod_tipo_parl, pley_num,
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
