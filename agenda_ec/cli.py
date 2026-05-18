"""CLI para agenda_ec.

Comandos:
  init     - Crea las tablas en proyectos_ec.db
  update   - Descarga ICS + parsea + upsert + matchea PLs
  rematch  - Solo re-corre el matching (sin re-descargar)
  stats    - Muestra conteos de sesiones y matches

Ejemplo:
  python -m agenda_ec.cli update --days-back 60 --days-fwd 120
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .schema import SCHEMA_AGENDA_EC
from .sync import rematch_all, sync


def _open(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def cmd_init(args: argparse.Namespace) -> int:
    conn = _open(args.db)
    with conn:
        conn.executescript(SCHEMA_AGENDA_EC)
    print(f"[init] schema aplicado en {args.db}")
    conn.close()
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    conn = _open(args.db)
    try:
        stats = sync(conn, days_back=args.days_back, days_fwd=args.days_fwd)
    finally:
        conn.close()
    print(f"[update] OK: {stats}")
    return 0


def cmd_rematch(args: argparse.Namespace) -> int:
    conn = _open(args.db)
    try:
        with conn:
            conn.executescript(SCHEMA_AGENDA_EC)
        total = rematch_all(conn)
    finally:
        conn.close()
    print(f"[rematch] {total} matches generados")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = _open(args.db)
    try:
        sesiones = conn.execute("SELECT COUNT(*) FROM sesiones_ec").fetchone()[0]
        proximas = conn.execute(
            "SELECT COUNT(*) FROM sesiones_ec WHERE fecha >= date('now')"
        ).fetchone()[0]
        con_pl = conn.execute(
            "SELECT COUNT(DISTINCT uid) FROM sesion_ec_pl_referenciado"
        ).fetchone()[0]
        matches = conn.execute(
            "SELECT COUNT(*) FROM sesion_ec_pl_referenciado"
        ).fetchone()[0]
        pls_distintos = conn.execute(
            "SELECT COUNT(DISTINCT n_tramite) FROM sesion_ec_pl_referenciado WHERE n_tramite IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    print(
        f"[stats] sesiones={sesiones} proximas={proximas} "
        f"con_pl={con_pl} matches={matches} pls_distintos={pls_distintos}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agenda_ec", description="Agenda EC sync")
    p.add_argument("--db", default="proyectos_ec.db", help="ruta al SQLite")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea tablas")

    pu = sub.add_parser("update", help="descarga ICS + sync + matching")
    pu.add_argument("--days-back", type=int, default=60)
    pu.add_argument("--days-fwd", type=int, default=120)

    sub.add_parser("rematch", help="re-corre matching de PLs (sin descargar)")
    sub.add_parser("stats", help="muestra estadisticas")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "update":
        return cmd_update(args)
    if args.cmd == "rematch":
        return cmd_rematch(args)
    if args.cmd == "stats":
        return cmd_stats(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
