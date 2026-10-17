"""CLI del scraper de agendas del Pleno.

Uso:
  python -m pleno.cli update
"""
from __future__ import annotations

import argparse
import logging

from pleno.db import Database
from pleno.from_agenda_pdf import sync_from_agenda_pdf

DEFAULT_DB = "proyectos.db"


def cmd_update(args) -> int:
    """Completa pleno_sesiones desde pleno_agenda_pdf, sin red. La API vieja
    (adp-portal) no publica el Congreso bicameral 2026-2031; sus agendas
    2011-2026 ya guardadas quedan como historia."""
    with Database(args.db) as db:
        db.init_schema()
        stats = sync_from_agenda_pdf(db)
    print(f"--- Pleno desde agenda_pdf --- vistos={stats['vistos']} "
          f"nuevos={stats['nuevos']} actualizados={stats['actualizados']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pleno",
        description="Scraper de agendas del Pleno del Congreso PE")
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default: {DEFAULT_DB})")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("update", help="corre sync incremental")
    up.set_defaults(func=cmd_update)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
