"""CLI del scraper de mesas de trabajo + eventos del Congreso PE.

Uso:
  python -m mesas_tecnicas.cli sync [--pages 5]
  python -m mesas_tecnicas.cli sync-dias [--days-back 14] [--days-fwd 21]
"""
from __future__ import annotations

import argparse
import logging
import sys

from mesas_tecnicas.db import Database
from mesas_tecnicas.scraper import run_sync


DEFAULT_DB = "proyectos.db"


def cmd_sync(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        run_id = db.start_sync_run()
        try:
            stats = run_sync(db, max_pages_rss=args.pages)
        except Exception as e:
            db.finish_sync_run(run_id, errores=1, mensaje=str(e)[:500])
            print(f"Error: {e}", file=sys.stderr)
            return 1
        db.finish_sync_run(run_id, **{
            k: v for k, v in stats.items()
            if k in ("vistos", "nuevos", "actualizados", "paginas_rss", "errores")
        })
        print(
            f"Sync terminado: paginas_rss={stats['paginas_rss']} "
            f"vistos={stats['vistos']} nuevos={stats['nuevos']} "
            f"actualizados={stats['actualizados']} errores={stats['errores']}"
        )
    return 0


def cmd_sync_dias(args) -> int:
    """Itera dias y enriquece horas usando URL directa /agenda/Y/M/D/.
    No requiere Playwright — HTTP simple."""
    from mesas_tecnicas.scraper import run_sync_dias
    with Database(args.db) as db:
        db.init_schema()
        stats = run_sync_dias(
            db,
            days_back=args.days_back,
            days_fwd=args.days_fwd,
        )
        print(f"\n[sync-dias] stats: {stats}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mesas_tecnicas",
        description="Scraper de mesas de trabajo + eventos del Congreso PE")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sy = sub.add_parser("sync", help="scrapea RSS + detalles")
    sy.add_argument("--pages", type=int, default=5,
                    help="paginas RSS a iterar (default 5 = 50 items recientes)")
    sy.set_defaults(func=cmd_sync)

    sd = sub.add_parser("sync-dias",
        help="itera dias usando URL directa /agenda/Y/M/D (sin Playwright)")
    sd.add_argument("--days-back", type=int, default=14)
    sd.add_argument("--days-fwd", type=int, default=21)
    sd.set_defaults(func=cmd_sync_dias)
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
