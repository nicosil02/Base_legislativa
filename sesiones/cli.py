"""CLI del scraper de sesiones.

Uso:
  python -m sesiones.cli init                       # crea tablas en proyectos.db
  python -m sesiones.cli update [--full] [--limit N] [--periodo-leg 2025]
  python -m sesiones.cli show <id_sesion>           # detalle + PLs cruzados
  python -m sesiones.cli list [--comision N] [--desde YYYY-MM-DD]
  python -m sesiones.cli stats
"""
from __future__ import annotations

import argparse
import logging
import sys

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
    los periodos del periodo parlamentario actual (2021-2026 = 2021..2025).
    """
    with Database(args.db) as db:
        db.init_schema()
        if args.periodo_leg == "all":
            # Periodo parlamentario 2021-2026 = legislaturas 2021, 22, 23, 24, 25
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


def cmd_show(args) -> int:
    with Database(args.db) as db:
        r = db.conn.execute(
            "SELECT * FROM sesiones WHERE id_sesion=?", (args.id_sesion,)
        ).fetchone()
        if r is None:
            print(f"Sesion {args.id_sesion} no encontrada en DB.", file=sys.stderr)
            return 1
        print(f"\nSesion {r['id_sesion']}  ({r['fecha']} {r['hora_inicio']}-{r['hora_fin']})")
        print(f"  Comision: {r['nombre_comision']}  [{r['tipo_comision']}]")
        print(f"  Nombre:   {r['nombre_sesion']}")
        print(f"  Estado:   {r['estado']}")
        if r['link_teams']:
            print(f"  Teams:    {r['link_teams']}")
        if r['link_video']:
            print(f"  Video:    {r['link_video']}")
        if r['id_alfresco_acta']:
            print(f"  Acta PDF: id alfresco {r['id_alfresco_acta']}")
        # Puntos de agenda
        puntos = db.conn.execute(
            "SELECT id_orden_dia, orden, descripcion_texto FROM sesion_agenda_punto "
            "WHERE id_sesion=? ORDER BY orden",
            (args.id_sesion,),
        ).fetchall()
        if puntos:
            print(f"\n  Puntos del orden del dia ({len(puntos)}):")
            for p in puntos:
                txt = (p['descripcion_texto'] or '')[:220].replace('\n', ' ')
                print(f"    {p['orden']+1}. ({p['id_orden_dia']}) {txt}{'...' if len(p['descripcion_texto'] or '') > 220 else ''}")
        # PLs cruzados con la tabla proyectos
        pls = db.conn.execute(
            """SELECT pr.pley_num, p.proyecto_ley, p.tema, p.estado, substr(p.titulo, 1, 60) AS titulo, pr.contexto
               FROM sesion_pl_referenciado pr
               LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
               WHERE pr.id_sesion=? ORDER BY pr.pley_num""",
            (args.id_sesion,),
        ).fetchall()
        if pls:
            print(f"\n  PLs referenciados en agenda ({len(pls)}):")
            for pl in pls:
                tema = pl['tema'] or '(no clasificado)'
                titulo = pl['titulo'] or '(no en DB)'
                print(f"    PL {pl['pley_num']:5d}  [{tema}]  {titulo}")
    return 0


def cmd_list(args) -> int:
    with Database(args.db) as db:
        sql = """SELECT id_sesion, fecha, hora_inicio, nombre_comision, estado,
                        (SELECT COUNT(*) FROM sesion_pl_referenciado WHERE id_sesion=s.id_sesion) AS n_pls
                 FROM sesiones s WHERE 1=1"""
        params: list = []
        if args.comision:
            sql += " AND comision_id = ?"
            params.append(args.comision)
        if args.desde:
            sql += " AND fecha >= ?"
            params.append(args.desde)
        if args.hasta:
            sql += " AND fecha <= ?"
            params.append(args.hasta)
        if args.estado:
            sql += " AND estado = ?"
            params.append(args.estado)
        sql += " ORDER BY fecha DESC, hora_inicio DESC"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = db.conn.execute(sql, params).fetchall()
        for r in rows:
            print(f"  {r['id_sesion']:5d} {r['fecha']} {r['hora_inicio'] or '?':7s} "
                  f"PLs={r['n_pls']:2d}  {(r['estado'] or '?')[:10]:10s} {r['nombre_comision']}")
        print(f"\n{len(rows)} sesion(es)")
    return 0


def cmd_stats(args) -> int:
    with Database(args.db) as db:
        total = db.count_sesiones()
        print(f"Total sesiones: {total}")
        print("\nPor estado:")
        for r in db.conn.execute(
            "SELECT estado, COUNT(*) AS c FROM sesiones GROUP BY estado ORDER BY c DESC"
        ):
            print(f"  {r['c']:4d}  {r['estado']}")
        print("\nPor comision (top 15):")
        for r in db.conn.execute(
            "SELECT nombre_comision, COUNT(*) AS c FROM sesiones "
            "GROUP BY nombre_comision ORDER BY c DESC LIMIT 15"
        ):
            print(f"  {r['c']:4d}  {r['nombre_comision']}")
        n_pls_unicos = db.conn.execute(
            "SELECT COUNT(DISTINCT pley_num) FROM sesion_pl_referenciado"
        ).fetchone()[0]
        n_refs = db.conn.execute("SELECT COUNT(*) FROM sesion_pl_referenciado").fetchone()[0]
        print(f"\nReferencias a PLs: {n_refs} total / {n_pls_unicos} PLs únicos")
        # Ultimo sync
        last = db.conn.execute(
            "SELECT * FROM sesiones_sync_runs WHERE finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last:
            print(f"\nUltimo sync ({last['mensaje']}): {last['finished_at']}")
            print(f"  vistas={last['sesiones_vistas']} nuevas={last['sesiones_nuevas']} "
                  f"actualizadas={last['sesiones_actualizadas']} errores={last['errores']}")
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
    up.add_argument("--periodo-par", dest="periodo_par", type=int, default=2021,
                    help="periodo parlamentario (default 2021)")
    up.add_argument("--periodo-leg", dest="periodo_leg", default="2025",
                    help="periodo legislativo: numero (2025) o 'all' para todos los del periodo parlamentario")
    up.set_defaults(func=cmd_update)

    sh = sub.add_parser("show", help="detalle de una sesion + PLs cruzados")
    sh.add_argument("id_sesion", type=int)
    sh.set_defaults(func=cmd_show)

    ls = sub.add_parser("list", help="lista sesiones con filtros")
    ls.add_argument("--comision", type=int, help="comision_id (1-24 ordinarias, 55 CP, etc.)")
    ls.add_argument("--estado")
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
