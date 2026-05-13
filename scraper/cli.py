"""CLI del scraper.

Uso:
  python -m scraper.cli init                       # crea DB y baja comisiones
  python -m scraper.cli update [--full] [--limit N]
  python -m scraper.cli export [--out proyectos.json]
  python -m scraper.cli query --comision 4
  python -m scraper.cli query --estado "EN COMISIÓN"
  python -m scraper.cli show 14515
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scraper.api import ApiClient
from scraper.db import Database
from scraper.export import export_json
from scraper.sync import PER_PAR_ID_ACTUAL, env_max_proyectos, run_sync

DEFAULT_DB = "proyectos.db"
DEFAULT_JSON = "proyectos.json"


def cmd_init(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        if db.count_comisiones() == 0:
            client = ApiClient()
            comis = client.list_comisiones()
            db.upsert_comisiones(comis)
            print(f"DB inicializada en {args.db} — {len(comis)} comisiones cargadas.")
        else:
            print(f"DB ya tenía {db.count_comisiones()} comisiones; esquema asegurado.")
    return 0


def cmd_update(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        max_p = args.limit if args.limit is not None else env_max_proyectos()
        stats = run_sync(db, full=args.full, max_proyectos=max_p)
        print(
            f"Sync terminado: vistos={stats.vistos} nuevos={stats.nuevos} "
            f"actualizados={stats.actualizados} detail_fetches={stats.detail_fetches} "
            f"errores={stats.errores}"
        )
    return 0


def cmd_export(args) -> int:
    with Database(args.db) as db:
        n = export_json(db, args.out)
        print(f"Exportados {n} proyectos a {args.out}")
    return 0


def cmd_query(args) -> int:
    with Database(args.db) as db:
        sql = (
            "SELECT p.per_par_id, p.pley_num, p.proyecto_ley, p.estado, p.fec_presentacion, "
            "       p.proponente, p.grupo_parlamentario, "
            "       GROUP_CONCAT(pc.nombre, ' | ') AS comisiones, p.titulo "
            "FROM proyectos p "
            "LEFT JOIN proyecto_comision pc USING (per_par_id, pley_num)"
        )
        where = []
        params: list = []
        if args.comision is not None:
            where.append("pc.comision_id = ?")
            params.append(args.comision)
        if args.estado:
            where.append("p.estado = ?")
            params.append(args.estado)
        if args.proponente:
            where.append("p.proponente = ?")
            params.append(args.proponente)
        if args.partido:
            where.append("p.grupo_parlamentario = ?")
            params.append(args.partido)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY p.per_par_id, p.pley_num ORDER BY p.fec_presentacion DESC LIMIT ?"
        params.append(args.limit)
        rows = db.conn.execute(sql, params).fetchall()
        for r in rows:
            print(
                f"{r['proyecto_ley']:18s} {r['estado']:22s} {r['fec_presentacion'][:10]} "
                f"{(r['proponente'] or '-'):12s} {(r['grupo_parlamentario'] or '-'):24s} "
                f"[{r['comisiones'] or '-'}] {r['titulo'][:70]}"
            )
        print(f"\n{len(rows)} resultado(s)")
    return 0


def cmd_show(args) -> int:
    with Database(args.db) as db:
        row = db.conn.execute(
            "SELECT * FROM proyectos WHERE per_par_id=? AND pley_num=?",
            (args.per_par_id, args.pley_num),
        ).fetchone()
        if not row:
            print(f"Proyecto {args.per_par_id}/{args.pley_num} no encontrado.", file=sys.stderr)
            return 1
        print(f"Proyecto de Ley: {row['proyecto_ley']}")
        print(f"Título: {row['titulo']}")
        print(f"Estado: {row['estado']}  (id={row['estado_id']})")
        print(f"Presentado: {row['fec_presentacion']}")
        print(f"Proponente: {row['proponente']}  Grupo: {row['grupo_parlamentario']}")
        print(f"Portal: {row['url_portal']}")
        if row["url_pdf"]:
            print(f"PDF: {row['url_pdf']}")
        if row["sumilla"]:
            print(f"\nSumilla:\n{row['sumilla']}")
        coms = db.conn.execute(
            "SELECT nombre FROM proyecto_comision WHERE per_par_id=? AND pley_num=?",
            (args.per_par_id, args.pley_num),
        ).fetchall()
        if coms:
            print("\nComisiones: " + ", ".join(c["nombre"] for c in coms))
        segs = db.conn.execute(
            "SELECT fecha, estado, comisiones, observacion FROM seguimientos "
            "WHERE per_par_id=? AND pley_num=? ORDER BY fecha DESC",
            (args.per_par_id, args.pley_num),
        ).fetchall()
        if segs:
            print("\nHistorial:")
            for s in segs:
                fecha = (s["fecha"] or "")[:10]
                line = f"  {fecha}  {s['estado']}"
                if s["comisiones"]:
                    line += f"  ({s['comisiones']})"
                print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scraper", description="Scraper de proyectos de ley del Congreso del Perú")
    p.add_argument("--db", default=DEFAULT_DB, help=f"Ruta del SQLite (default: {DEFAULT_DB})")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea DB y carga comisiones").set_defaults(func=cmd_init)

    up = sub.add_parser("update", help="corre sync incremental")
    up.add_argument("--full", action="store_true", help="re-enriquece todos los proyectos (no solo los cambiados)")
    up.add_argument("--limit", type=int, default=None, help="máximo de proyectos a procesar")
    up.set_defaults(func=cmd_update)

    ex = sub.add_parser("export", help="exporta a JSON")
    ex.add_argument("--out", default=DEFAULT_JSON)
    ex.set_defaults(func=cmd_export)

    q = sub.add_parser("query", help="lista proyectos con filtros")
    q.add_argument("--comision", type=int)
    q.add_argument("--estado")
    q.add_argument("--proponente", help="ej. Congreso, Ejecutivo, Ciudadanos, Regional")
    q.add_argument("--partido", help="grupo parlamentario exacto, ej. 'Perú Libre'")
    q.add_argument("--limit", type=int, default=50)
    q.set_defaults(func=cmd_query)

    sh = sub.add_parser("show", help="muestra un proyecto e historial")
    sh.add_argument("pley_num", type=int)
    sh.add_argument("--per-par-id", dest="per_par_id", type=int, default=PER_PAR_ID_ACTUAL)
    sh.set_defaults(func=cmd_show)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
