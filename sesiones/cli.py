"""CLI del scraper de sesiones.

Uso:
  python -m sesiones.cli init                       # crea tablas en proyectos.db
  python -m sesiones.cli update [--full] [--limit N] [--periodo-leg 2025|all]
"""
from __future__ import annotations

import argparse
import logging

from sesiones.db import Database
from sesiones.sync import run_sync

DEFAULT_DB = "proyectos.db"


def cmd_init(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        print(f"Tablas de sesiones creadas/aseguradas en {args.db}")
        print(f"  Sesiones existentes: {db.count_sesiones()}")
    return 0


def cmd_update(args) -> int:
    """Sincroniza sesiones de uno o varios periodos legislativos.

    Si --periodo-leg es entero: solo ese año. Si es 'all': itera todos
    los periodos del periodo parlamentario actual (2026-2031 = 2026..2030).
    """
    with Database(args.db) as db:
        db.init_schema()
        if args.periodo_leg == "all":
            # Periodo parlamentario 2026-2031 = legislaturas 2026, 27, 28, 29, 30
            anios = list(range(args.periodo_par, args.periodo_par + 5))
        else:
            anios = [int(args.periodo_leg)]

        total_vistas = total_nuevas = total_act = total_err = 0
        for anio in anios:
            print(f"\n--- Sync periodo legislativo {anio} ---")
            stats = run_sync(
                db,
                periodo_parlamentario=args.periodo_par,
                periodo_legislativo=anio,
                full=args.full,
                max_sesiones=args.limit,
            )
            total_vistas += stats.vistas
            total_nuevas += stats.nuevas
            total_act += stats.actualizadas
            total_err += stats.errores
            print(
                f"  vistas={stats.vistas} nuevas={stats.nuevas} "
                f"actualizadas={stats.actualizadas} errores={stats.errores}"
            )
        if len(anios) > 1:
            print(
                f"\nTotal {len(anios)} periodos: vistas={total_vistas} "
                f"nuevas={total_nuevas} actualizadas={total_act} errores={total_err}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sesiones",
        description="Scraper de sesiones de comisiones del Congreso PE")
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default: {DEFAULT_DB})")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea las tablas sesion_* en la DB").set_defaults(func=cmd_init)

    up = sub.add_parser("update", help="corre sync incremental")
    up.add_argument("--full", action="store_true", help="re-fetchea detalle de todas")
    up.add_argument("--limit", type=int, default=None, help="max sesiones a procesar")
    up.add_argument("--periodo-par", dest="periodo_par", type=int, default=2026,
                    help="periodo parlamentario (default 2026 = 2026-2031, Congreso bicameral vigente)")
    up.add_argument("--periodo-leg", dest="periodo_leg", default="2026",
                    help="periodo legislativo: numero (2026) o 'all' para todos los del periodo parlamentario")
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
