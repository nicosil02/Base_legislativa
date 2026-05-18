"""Schema SQL para tablas de agenda parlamentaria EC.

Se aplica sobre proyectos_ec.db (mismo SQLite que los proyectos para
poder hacer JOINs entre PL y sesion sin tocar dos conexiones).
"""
from __future__ import annotations

SCHEMA_AGENDA_EC = """
-- Sesiones (VEVENTs del calendario Zimbra de la Asamblea Nacional).
CREATE TABLE IF NOT EXISTS sesiones_ec (
  uid             TEXT PRIMARY KEY,         -- UID del VEVENT
  summary         TEXT NOT NULL,            -- "Sesion de la Comision X, modalidad virtual"
  nombre_comision TEXT,                     -- extraido del summary
  modalidad       TEXT,                     -- "virtual" / "presencial" / NULL
  fecha           TEXT NOT NULL,            -- YYYY-MM-DD (DTSTART en hora local EC)
  hora_inicio     TEXT,                     -- HH:MM
  hora_fin        TEXT,                     -- HH:MM
  descripcion     TEXT,                     -- DESCRIPTION (texto plano, ya unescapado)
  location        TEXT,
  status          TEXT,                     -- CONFIRMED / TENTATIVE / CANCELLED
  last_modified   TEXT,                     -- LAST-MODIFIED del ICS
  captured_at     TEXT NOT NULL             -- cuando lo bajamos
);

CREATE INDEX IF NOT EXISTS idx_sesion_ec_fecha    ON sesiones_ec(fecha);
CREATE INDEX IF NOT EXISTS idx_sesion_ec_comision ON sesiones_ec(nombre_comision);
CREATE INDEX IF NOT EXISTS idx_sesion_ec_status   ON sesiones_ec(status);

-- Cross-reference: que PLs se debaten en cada sesion.
-- Se llena por matching de substrings normalizados del titulo del PL
-- contra el campo descripcion de la sesion.
CREATE TABLE IF NOT EXISTS sesion_ec_pl_referenciado (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  uid         TEXT NOT NULL,
  n_tramite   TEXT,                  -- FK a proyectos.n_tramite (puede ser NULL si no matcheo)
  match_text  TEXT,                  -- substring del titulo que matcheo
  score       REAL,                  -- 0..1, longitud match / longitud titulo
  FOREIGN KEY (uid) REFERENCES sesiones_ec(uid) ON DELETE CASCADE,
  FOREIGN KEY (n_tramite) REFERENCES proyectos(n_tramite)
);

CREATE INDEX IF NOT EXISTS idx_sespl_ec_uid     ON sesion_ec_pl_referenciado(uid);
CREATE INDEX IF NOT EXISTS idx_sespl_ec_tramite ON sesion_ec_pl_referenciado(n_tramite);
"""
