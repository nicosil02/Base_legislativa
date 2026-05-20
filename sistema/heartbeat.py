"""Heartbeats de workflows.

Cada workflow llama `python -m sistema.heartbeat --db DB --source NAME`
al final de una corrida exitosa. Esto deja huella en la tabla
`system_heartbeats` aunque los datos del Congreso/Asamblea no hayan
cambiado (importante para el "actualizado hace X min" en la UI: el
usuario quiere saber si el workflow corre, no si los datos cambian).

Schema:
  system_heartbeats (
    source TEXT PRIMARY KEY,    -- 'pe_proyectos', 'pe_sesiones', 'ec_proyectos', 'ec_agenda'
    last_run TEXT NOT NULL,     -- timestamp ISO UTC de la ultima corrida exitosa
    last_status TEXT            -- 'ok' | 'partial' | 'failed'
  )
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone


SCHEMA = """
CREATE TABLE IF NOT EXISTS system_heartbeats (
  source       TEXT PRIMARY KEY,
  last_run     TEXT NOT NULL,
  last_status  TEXT NOT NULL DEFAULT 'ok'
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(db_path: str, source: str, status: str = "ok") -> None:
    """Registra un heartbeat. Crea la tabla si no existe."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO system_heartbeats (source, last_run, last_status) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET "
            "  last_run = excluded.last_run, "
            "  last_status = excluded.last_status",
            (source, now_iso(), status),
        )
        conn.commit()
    finally:
        conn.close()


def get_all(db_path: str) -> dict[str, tuple[str, str]]:
    """Devuelve {source: (last_run, last_status)} de todos los heartbeats
    en la DB. Devuelve {} si la tabla no existe todavia."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return {}
    try:
        try:
            rows = conn.execute(
                "SELECT source, last_run, last_status FROM system_heartbeats"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {r[0]: (r[1], r[2]) for r in rows}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sistema.heartbeat",
        description="Registra un heartbeat de workflow")
    p.add_argument("--db", required=True, help="ruta al SQLite")
    p.add_argument("--source", required=True,
        help="identificador de la fuente (ej. pe_proyectos)")
    p.add_argument("--status", default="ok",
        choices=["ok", "partial", "failed"],
        help="estado de la corrida")
    args = p.parse_args(argv)
    record(args.db, args.source, args.status)
    print(f"[heartbeat] {args.source} -> {args.status} @ {now_iso()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
