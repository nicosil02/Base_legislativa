"""CLI del scraper de mesas de trabajo + eventos del Congreso PE.

Uso:
  python -m mesas_tecnicas.cli init                            # crea tablas
  python -m mesas_tecnicas.cli sync [--pages 5] [--no-details]
  python -m mesas_tecnicas.cli list [--desde YYYY-MM-DD] [--limit 20]
  python -m mesas_tecnicas.cli stats
"""
from __future__ import annotations

import argparse
import logging
import sys

from mesas_tecnicas.db import Database
from mesas_tecnicas.scraper import run_sync


DEFAULT_DB = "proyectos.db"


def cmd_init(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        print(f"Tablas mesas_tecnicas creadas/aseguradas en {args.db}")
        print(f"  Filas existentes: {db.count()}")
    return 0


def cmd_sync(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        run_id = db.start_sync_run()
        try:
            stats = run_sync(
                db,
                max_pages_rss=args.pages,
                fetch_details=not args.no_details,
                include_listing_hoy=not args.no_listing,
            )
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


def cmd_list(args) -> int:
    with Database(args.db) as db:
        sql = "SELECT * FROM mesas_tecnicas WHERE 1=1"
        params: list = []
        if args.desde:
            # Comparamos por fecha si la tenemos, sino por pub_date
            sql += " AND (fecha >= ? OR pub_date >= ?)"
            params.extend([args.desde, args.desde])
        sql += " ORDER BY COALESCE(fecha, '') DESC, hora DESC LIMIT ?"
        params.append(args.limit)
        rows = db.conn.execute(sql, params).fetchall()
        for r in rows:
            fecha = r["fecha"] or (r["pub_date"] or "")[:10]
            hora = (r["hora"] or "?")[:9]
            tipo = (r["tipo"] or "")[:18]
            tema = (r["tema"] or r["titulo"] or "")[:60]
            organiza = (r["congresista"] or r["organiza"] or "")[:35]
            print(f"  {fecha} {hora:9s} {tipo:18s} | {tema:60s} | {organiza}")
        print(f"\n{len(rows)} fila(s)")
    return 0


def cmd_stats(args) -> int:
    with Database(args.db) as db:
        total = db.count()
        print(f"Total mesas/eventos: {total}")
        print("\nPor tipo:")
        for r in db.conn.execute(
            "SELECT tipo, COUNT(*) c FROM mesas_tecnicas GROUP BY tipo ORDER BY c DESC"
        ):
            print(f"  {r['c']:5d}  {r['tipo']}")
        print("\nUltimo sync:")
        last = db.conn.execute(
            "SELECT * FROM mesas_tecnicas_sync_runs "
            "WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last:
            print(f"  {last['finished_at']} (vistos={last['vistos']} "
                  f"nuevos={last['nuevos']} actualizados={last['actualizados']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mesas_tecnicas",
        description="Scraper de mesas de trabajo + eventos del Congreso PE")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea las tablas").set_defaults(func=cmd_init)

    sy = sub.add_parser("sync", help="scrapea RSS + detalles")
    sy.add_argument("--pages", type=int, default=5,
                    help="paginas RSS a iterar (default 5 = 50 items recientes)")
    sy.add_argument("--no-details", action="store_true",
                    help="no fetchear el HTML de cada post (mas rapido pero sin detalles)")
    sy.add_argument("--no-listing", action="store_true",
                    help="no leer /agenda/ del dia (skip merge de hora real)")
    sy.set_defaults(func=cmd_sync)

    ls = sub.add_parser("list", help="lista los items")
    ls.add_argument("--desde", help="YYYY-MM-DD")
    ls.add_argument("--limit", type=int, default=30)
    ls.set_defaults(func=cmd_list)

    sub.add_parser("stats", help="estadisticas").set_defaults(func=cmd_stats)
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
