"""CLI del scraper de agendas del Pleno.

Uso:
  python -m pleno.cli init                                   # crea tablas pleno_* en proyectos.db
  python -m pleno.cli update [--full] [--limit N] [--periodo 2021-2026|all]
  python -m pleno.cli show <cod_agenda>                      # detalle + PLs cruzados
  python -m pleno.cli list [--desde YYYY-MM-DD] [--hasta YYYY-MM-DD]
  python -m pleno.cli stats
"""
from __future__ import annotations

import argparse
import logging
import sys

from pleno.db import Database
from pleno.sync import run_sync

DEFAULT_DB = "proyectos.db"


def cmd_init(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        print(f"Tablas del Pleno creadas/aseguradas en {args.db}")
        print(f"  Agendas existentes: {db.count_agendas()}")
    return 0


def cmd_update(args) -> int:
    """Sincroniza agendas del Pleno. Default periodo = '2021-2026'.
    Para traer TODO el historico (2011-presente) pasar `--periodo all`.
    """
    with Database(args.db) as db:
        db.init_schema()
        periodo = None if args.periodo == "all" else args.periodo
        print(f"--- Sync Pleno periodo={periodo or 'TODOS'} ---")
        stats = run_sync(
            db,
            periodo_filtro=periodo,
            full=args.full,
            max_agendas=args.limit,
        )
        print(
            f"  vistas={stats.vistas} nuevas={stats.nuevas} "
            f"actualizadas={stats.actualizadas} detail_fetches={stats.detail_fetches} "
            f"errores={stats.errores}"
        )
    return 0


def cmd_show(args) -> int:
    with Database(args.db) as db:
        r = db.conn.execute(
            "SELECT * FROM pleno_sesiones WHERE cod_agenda=?", (args.cod_agenda,)
        ).fetchone()
        if r is None:
            print(f"Agenda {args.cod_agenda} no encontrada.", file=sys.stderr)
            return 1
        print(f"\nAgenda {r['cod_agenda']}  ({r['fecha_sesion']})")
        print(f"  Periodo:     {r['periodo']}")
        print(f"  Legislatura: {r['legislatura']}")
        print(f"  Titulo:      {r['titulo']}")
        print(f"  Presidente:  {r['presidente']}")
        temas = db.conn.execute(
            "SELECT cod_tema, num_tema, des_sec, nom_tema_cor, des_comisiones "
            "FROM pleno_tema WHERE cod_agenda=? ORDER BY num_tema",
            (args.cod_agenda,),
        ).fetchall()
        if temas:
            print(f"\n  Temas en agenda ({len(temas)}):")
            for t in temas[:30]:
                com = t['des_comisiones'] or '—'
                print(f"    {t['num_tema']:3d}. [{t['des_sec']}] {t['nom_tema_cor']}  ({com})")
            if len(temas) > 30:
                print(f"    ... ({len(temas)-30} mas)")
        pls = db.conn.execute(
            """SELECT pr.pley_num, p.proyecto_ley, p.tema, p.estado,
                      substr(p.titulo,1,60) AS titulo, pr.origen
               FROM pleno_pl_referenciado pr
               LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
               WHERE pr.cod_agenda=? ORDER BY pr.pley_num""",
            (args.cod_agenda,),
        ).fetchall()
        if pls:
            print(f"\n  PLs referenciados en agenda ({len(pls)}):")
            for pl in pls[:30]:
                tema = pl['tema'] or '(no clasificado)'
                titulo = pl['titulo'] or '(no en DB)'
                print(f"    PL {pl['pley_num']:5d}  [{tema}]  {titulo}  via {pl['origen']}")
            if len(pls) > 30:
                print(f"    ... ({len(pls)-30} mas)")
    return 0


def cmd_list(args) -> int:
    with Database(args.db) as db:
        sql = """SELECT cod_agenda, fecha_sesion, titulo,
                        (SELECT COUNT(*) FROM pleno_tema WHERE cod_agenda=ps.cod_agenda) AS n_temas,
                        (SELECT COUNT(*) FROM pleno_pl_referenciado WHERE cod_agenda=ps.cod_agenda) AS n_pls
                 FROM pleno_sesiones ps WHERE 1=1"""
        params: list = []
        if args.desde:
            sql += " AND fecha_sesion >= ?"; params.append(args.desde)
        if args.hasta:
            sql += " AND fecha_sesion <= ?"; params.append(args.hasta)
        sql += " ORDER BY fecha_sesion DESC"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = db.conn.execute(sql, params).fetchall()
        for r in rows:
            print(f"  {r['cod_agenda']:4d} {r['fecha_sesion']} temas={r['n_temas']:3d} PLs={r['n_pls']:3d}  {r['titulo']}")
        print(f"\n{len(rows)} agenda(s)")
    return 0


def cmd_stats(args) -> int:
    with Database(args.db) as db:
        total = db.count_agendas()
        print(f"Total agendas del Pleno: {total}")
        print("\nPor periodo:")
        for r in db.conn.execute(
            "SELECT periodo, COUNT(*) AS c, MIN(fecha_sesion) AS desde, MAX(fecha_sesion) AS hasta "
            "FROM pleno_sesiones GROUP BY periodo ORDER BY periodo"
        ):
            print(f"  {r['c']:3d}  {r['periodo']}  ({r['desde']} -> {r['hasta']})")
        n_pls_unicos = db.conn.execute(
            "SELECT COUNT(DISTINCT pley_num) FROM pleno_pl_referenciado"
        ).fetchone()[0]
        n_refs = db.conn.execute("SELECT COUNT(*) FROM pleno_pl_referenciado").fetchone()[0]
        print(f"\nReferencias a PLs: {n_refs} total / {n_pls_unicos} PLs únicos")
        last = db.conn.execute(
            "SELECT * FROM pleno_sync_runs WHERE finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last:
            print(f"\nUltimo sync ({last['mensaje']}): {last['finished_at']}")
            print(f"  vistas={last['agendas_vistas']} nuevas={last['agendas_nuevas']} "
                  f"actualizadas={last['agendas_actualizadas']} errores={last['errores']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pleno",
        description="Scraper de agendas del Pleno del Congreso PE")
    p.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default: {DEFAULT_DB})")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea las tablas pleno_* en la DB").set_defaults(func=cmd_init)

    up = sub.add_parser("update", help="corre sync incremental")
    up.add_argument("--full", action="store_true", help="re-fetchea detalle de todas")
    up.add_argument("--limit", type=int, default=None, help="max agendas a procesar")
    up.add_argument("--periodo", default="2021-2026",
                    help="periodo parlamentario (default 2021-2026; usar 'all' para todo desde 2011)")
    up.set_defaults(func=cmd_update)

    sh = sub.add_parser("show", help="detalle de una agenda + PLs cruzados")
    sh.add_argument("cod_agenda", type=int)
    sh.set_defaults(func=cmd_show)

    ls = sub.add_parser("list", help="lista agendas con filtros")
    ls.add_argument("--desde", help="YYYY-MM-DD")
    ls.add_argument("--hasta", help="YYYY-MM-DD")
    ls.add_argument("--limit", type=int, default=50)
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
