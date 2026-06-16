"""CLI del modulo de noticias."""
from __future__ import annotations

import argparse
import logging
import sys

from noticias.db import Database
from noticias.fuentes import all_fuentes
from noticias.scraper import run_sync


DEFAULT_DB = "proyectos.db"


def cmd_init(args) -> int:
    with Database(args.db) as db:
        db.init_schema()
        print(f"Tablas noticias creadas/aseguradas en {args.db}")
        print(f"  Fuentes activas: {db.count_fuentes()}")
        print(f"  Noticias capturadas: {db.count_noticias()}")
    return 0


def cmd_seed(args) -> int:
    """Importa el catalogo de fuentes desde noticias.fuentes."""
    with Database(args.db) as db:
        db.init_schema()
        n = 0
        for row in all_fuentes():
            db.upsert_fuente(row)
            n += 1
        print(f"Catalogo importado: {n} fuentes upserteadas.")
        print(f"  Activas en DB: {db.count_fuentes()}")
    return 0


def cmd_list_fuentes(args) -> int:
    with Database(args.db) as db:
        fuentes = db.list_fuentes(
            pais=args.pais, categoria=args.categoria,
            solo_activas=not args.todas,
        )
        if args.scrapeables:
            fuentes = [f for f in fuentes if f["tipo"] in ("rss", "html", "api")]
        if not fuentes:
            print("Sin fuentes con esos filtros.")
            return 0
        print(f"{len(fuentes)} fuente(s):\n")
        # Agrupar por categoria
        cat_actual = None
        for f in fuentes:
            if f["categoria"] != cat_actual:
                cat_actual = f["categoria"]
                print(f"\n=== {cat_actual} ===")
            tipo_marker = {
                "rss": "📡", "html": "🌐", "api": "⚙️",
                "twitter": "🐦", "manual": "✋",
            }.get(f["tipo"], "?")
            print(f"  {tipo_marker} [{f['pais']}] {f['nombre']}")
            if f["url"]:
                print(f"        url: {f['url']}")
            if f["rss_url"]:
                print(f"        rss: {f['rss_url']}")
    return 0


def cmd_sync(args) -> int:
    """Scrapea todas las fuentes activas (filtrables por pais/categoria)."""
    with Database(args.db) as db:
        db.init_schema()
        run_id = db.start_sync_run()
        try:
            stats = run_sync(
                db, pais=args.pais, categoria=args.categoria,
            )
        except Exception as e:
            db.finish_sync_run(run_id, errores=1, mensaje=str(e)[:500])
            print(f"Error: {e}", file=sys.stderr)
            return 1
        db.finish_sync_run(run_id, **{
            "fuentes_visitadas": stats["fuentes"],
            "noticias_nuevas": stats["nuevos"],
            "noticias_actualizadas": stats["actualizados"],
            "errores": stats["errores"],
        })
        print(
            f"Sync terminado: fuentes={stats['fuentes']} "
            f"items={stats['items_vistos']} nuevos={stats['nuevos']} "
            f"actualizados={stats['actualizados']} errores={stats['errores']}"
        )
    return 0


def cmd_stats(args) -> int:
    with Database(args.db) as db:
        print(f"Fuentes activas: {db.count_fuentes()}")
        print(f"Noticias totales: {db.count_noticias()}")
        print("\nPor categoria + pais:")
        rows = db.conn.execute(
            """SELECT f.pais, f.categoria, COUNT(n.id) AS n_noticias,
                      COUNT(DISTINCT f.id) AS n_fuentes
               FROM noticias_fuentes f
               LEFT JOIN noticias n ON n.fuente_id = f.id
               WHERE f.activa=1
               GROUP BY f.pais, f.categoria
               ORDER BY f.pais, f.categoria"""
        ).fetchall()
        for r in rows:
            print(f"  [{r['pais']}] {r['categoria']:30s} "
                  f"fuentes={r['n_fuentes']:3d} noticias={r['n_noticias']:6d}")
        print("\nUltimo sync:")
        last = db.conn.execute(
            "SELECT * FROM noticias_sync_runs WHERE finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last:
            print(f"  {last['finished_at']} (fuentes={last['fuentes_visitadas']} "
                  f"nuevos={last['noticias_nuevas']} "
                  f"actualizados={last['noticias_actualizadas']})")
    return 0


def cmd_purge(args) -> int:
    """Borra noticias mas viejas que --dias dias (default 7)."""
    with Database(args.db) as db:
        db.init_schema()
        n = db.purge_noticias_antiguas(args.dias)
        if n > 0:
            db.conn.execute("VACUUM")
        print(f"Eliminadas {n} noticia(s) anteriores a {args.dias} dia(s).")
        print(f"Quedan {db.count_noticias()} noticia(s) en la base.")
    return 0


def cmd_set_url(args) -> int:
    """Actualiza url y/o rss_url de una fuente por nombre+pais."""
    with Database(args.db) as db:
        with db.tx() as c:
            cur = c.execute(
                """UPDATE noticias_fuentes SET
                   url=COALESCE(?, url),
                   rss_url=COALESCE(?, rss_url),
                   tipo=COALESCE(?, tipo)
                   WHERE pais=? AND nombre=?""",
                (args.url, args.rss, args.tipo, args.pais, args.nombre),
            )
            if cur.rowcount == 0:
                print(f"No encontre fuente con pais={args.pais!r} nombre={args.nombre!r}")
                return 1
        print(f"Actualizada fuente {args.nombre} [{args.pais}]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="noticias",
        description="Mapeo de noticias PE + EC")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="crea tablas").set_defaults(func=cmd_init)

    sub.add_parser("seed",
        help="importa catalogo desde noticias.fuentes").set_defaults(func=cmd_seed)

    lf = sub.add_parser("list-fuentes", help="lista las fuentes catalogadas")
    lf.add_argument("--pais", choices=["PE", "EC"])
    lf.add_argument("--categoria")
    lf.add_argument("--todas", action="store_true", help="incluir inactivas")
    lf.add_argument("--scrapeables", action="store_true",
                    help="solo rss/html/api")
    lf.set_defaults(func=cmd_list_fuentes)

    sy = sub.add_parser("sync", help="scrapea fuentes y captura noticias")
    sy.add_argument("--pais", choices=["PE", "EC"])
    sy.add_argument("--categoria")
    sy.set_defaults(func=cmd_sync)

    sub.add_parser("stats", help="estadisticas").set_defaults(func=cmd_stats)

    pu = sub.add_parser("purge", help="borra noticias mas viejas que N dias")
    pu.add_argument("--dias", type=int, default=7,
                    help="dias a conservar (default 7)")
    pu.set_defaults(func=cmd_purge)

    su = sub.add_parser("set-url", help="actualiza url/rss de una fuente")
    su.add_argument("--pais", required=True, choices=["PE", "EC"])
    su.add_argument("--nombre", required=True)
    su.add_argument("--url")
    su.add_argument("--rss")
    su.add_argument("--tipo", choices=["rss", "html", "api", "twitter", "manual"])
    su.set_defaults(func=cmd_set_url)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
