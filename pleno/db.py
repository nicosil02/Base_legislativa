"""Capa de almacenamiento SQLite para sesiones del Pleno del Congreso.

Comparte el archivo `proyectos.db` con scraper/, sesiones/ y la app. Las tablas
usan prefijo `pleno_` para no chocar con las demas. El cruce con PLs usa el
mismo identificador (`pley_num`, INT) que ya estan usando todos los modulos.
"""
from __future__ import annotations

from core.db import Database as _Base

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
  camara               TEXT,                    -- 'D'/'S'/'C'/NULL; la API vieja no la trae
  fuente               TEXT DEFAULT 'api',      -- 'api' (adp-portal-service) | 'agenda_pdf'
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
  per_par_id           INTEGER NOT NULL DEFAULT 2026,
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


class Database(_Base):
    """Tablas `pleno_*` (comparte archivo con scraper/ y sesiones/)."""

    def init_schema(self) -> None:
        with self.tx() as c:
            c.executescript(SCHEMA)
