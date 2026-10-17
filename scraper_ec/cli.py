"""CLI del scraper Ecuador.

Ejemplos de uso:

    python -m scraper_ec.cli init
    python -m scraper_ec.cli importar-csv data/ppless_listado_2025-2029_snapshot.csv
    python -m scraper_ec.cli actualizar-csv
    python -m scraper_ec.cli enriquecer-documentos --limit 20
    python -m scraper_ec.cli scrapear-unificados
    python -m scraper_ec.cli recategorizar
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DB = "proyectos_ec.db"


def _db(args) -> "Database":
    from scraper_ec.db import Database
    db = Database(args.db)
    db.init_schema()
    return db


def cmd_init(args) -> int:
    db = _db(args)
    print(f"DB inicializada en {db.path}")
    print(f"Proyectos actuales: {db.count_proyectos()}")
    db.close()
    return 0


def cmd_importar_csv(args) -> int:
    from scraper_ec.csv_importer import import_csv
    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"ERROR: no encontré el CSV en {csv_path}")
        return 1

    db = _db(args)
    try:
        stats = import_csv(csv_path, db)
    finally:
        db.close()

    print(f"\nImport completado desde: {csv_path.name}")
    print(f"  vistos:        {stats['vistos']:>5}")
    print(f"  nuevos:        {stats['nuevos']:>5}")
    print(f"  actualizados:  {stats['actualizados']:>5}")
    print(f"  errores:       {stats['errores']:>5}")
    if stats["cambios_por_campo"]:
        print("\nCambios detectados por campo:")
        for campo, n in sorted(stats["cambios_por_campo"].items(), key=lambda x: -x[1]):
            print(f"  {campo:<25} {n}")
    return 0


def cmd_actualizar_csv(args) -> int:
    """Descarga el CSV fresco del portal Ppless v2 (Playwright) y lo importa."""
    from scraper_ec.playwright_detail import download_csv
    from scraper_ec.csv_importer import import_csv

    repo_root = Path(__file__).resolve().parent.parent
    # Archivo aparte (gitignored): pisar el seed versionado ensuciaba el
    # working tree y rompía el rebase del auto-commit.
    csv_path = repo_root / "data" / "ppless_actual.csv"

    print(f"[actualizar-csv] descargando CSV fresco a {csv_path.name}...")
    ok = download_csv(csv_path, headless=not args.no_headless)
    if not ok:
        print("[actualizar-csv] FALLO la descarga. Aborto.")
        return 1

    db = _db(args)
    try:
        print("[actualizar-csv] importando a DB...")
        stats = import_csv(csv_path, db)
        print(f"  vistos:        {stats['vistos']:>5}")
        print(f"  nuevos:        {stats['nuevos']:>5}")
        print(f"  actualizados:  {stats['actualizados']:>5}")
        print(f"  errores:       {stats['errores']:>5}")
        if stats["cambios_por_campo"]:
            print("\n  Cambios por campo:")
            for campo, n in sorted(stats["cambios_por_campo"].items(), key=lambda x: -x[1]):
                print(f"    {campo:<25} {n}")
    finally:
        db.close()
    return 0


def cmd_enriquecer_documentos(args) -> int:
    """Abre el detalle de cada proyecto con Playwright y guarda los PDFs."""
    try:
        from scraper_ec.playwright_detail import enrich_documentos
    except ImportError:
        print("Falta playwright. Instalá con: pip install playwright && python -m playwright install chromium")
        return 1

    db = _db(args)
    try:
        # Default: sin documentos o con cambio de estado en 14 días (cada fase
        # sube PDFs nuevos). --force ignora el filtro.
        params: list = []
        sql = "SELECT n_tramite FROM proyectos"
        where = []
        if args.estado:
            where.append("estado = ?")
            params.append(args.estado)
        if getattr(args, "solo_sin_fase", False):
            where.append(
                "n_tramite IN (SELECT DISTINCT n_tramite FROM documentos "
                "WHERE fase IS NULL OR fase = '')"
            )
        elif not args.force:
            where.append(
                "(n_tramite NOT IN (SELECT DISTINCT n_tramite FROM documentos) "
                "OR n_tramite IN (SELECT n_tramite FROM historial_cambios "
                "WHERE campo = 'estado' AND changed_at > "
                "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-14 days')))"
            )
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Los sin documentos primero, luego los mas recientes.
        sql += (" ORDER BY n_tramite IN (SELECT n_tramite FROM documentos),"
                " fec_presentacion DESC")
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        n_tramites = [r["n_tramite"] for r in db.conn.execute(sql, params).fetchall()]

        def progress(ntr, idx, total):
            print(f"[{idx}/{total}] {ntr}")

        stats = enrich_documentos(
            db,
            n_tramites=n_tramites,
            headless=not args.no_headless,
            on_progress=progress,
            sleep_between_ms=args.sleep_ms,
        )
        print("\nResumen:")
        for k, v in stats.items():
            print(f"  {k:<14} {v}")
    finally:
        db.close()
    return 0


def cmd_recategorizar(args) -> int:
    db = _db(args)
    try:
        # Solo re-clasifica los que no son manuales
        n = 0
        for r in db.conn.execute(
            "SELECT n_tramite, titulo FROM proyectos WHERE tema_manual = 0"
        ).fetchall():
            db.classify_and_save(r["n_tramite"], r["titulo"])
            n += 1
        print(f"Re-clasificados (no manuales): {n}")
    finally:
        db.close()
    return 0


def cmd_scrapear_unificados(args) -> int:
    """Reemplaza los grupos source='portal' por los que muestra el portal."""
    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    from scraper_ec.playwright_unificado import scrapear_unificados
    stats = scrapear_unificados(
        db_path=args.db,
        headless=not args.no_headless,
        max_pages=args.max_pages,
    )
    print(f"\n[scrapear-unificados] stats: {stats}")
    return 0


def cmd_marcar_unificacion(args) -> int:
    """Crea un grupo de unificación con los PLs dados (--pls 480824,480825)."""
    db = _db(args)
    try:
        n_tramites = [s.strip() for s in args.pls.split(",") if s.strip()]
        if not n_tramites:
            print("Error: --pls vacio")
            return 1
        # Validar que todos existan
        existentes = {
            r[0] for r in db.conn.execute(
                f"SELECT n_tramite FROM proyectos WHERE n_tramite IN ({','.join('?'*len(n_tramites))})",
                n_tramites,
            )
        }
        no_existen = [n for n in n_tramites if n not in existentes]
        if no_existen:
            print(f"[warn] PLs no encontrados en la DB: {no_existen}")
        validos = [n for n in n_tramites if n in existentes]
        if not validos:
            print("Error: ningun PL valido")
            return 1
        grupo_id = db.crear_grupo_unificacion(
            n_tramites=validos,
            nombre=args.nombre,
            descripcion=args.descripcion,
            n_tramite_principal=args.principal,
        )
        print(f"Grupo {grupo_id} creado con {len(validos)} PLs:")
        for n in validos:
            marca = " (principal)" if n == (args.principal or validos[0]) else ""
            print(f"  - {n}{marca}")
    finally:
        db.close()
    return 0


def cmd_listar_unificaciones(args) -> int:
    """Lista todos los grupos de unificacion con sus miembros."""
    db = _db(args)
    try:
        grupos = db.listar_grupos_unificacion()
        if not grupos:
            print("No hay grupos de unificacion registrados.")
            return 0
        print(f"{len(grupos)} grupo(s) de unificacion:\n")
        for g in grupos:
            nombre = g.get("nombre") or "(sin nombre)"
            print(f"  #{g['id']:3d}  [{g['n_pls']:2d} PLs]  {nombre}")
            print(f"        principal: {g['n_tramite_principal']}")
            print(f"        miembros: {g['miembros']}")
            print(f"        source={g['source']}  created={g['created_at']}")
            print()
    finally:
        db.close()
    return 0


def cmd_borrar_unificacion(args) -> int:
    db = _db(args)
    try:
        db.borrar_grupo_unificacion(args.grupo_id)
        print(f"Grupo {args.grupo_id} borrado.")
    finally:
        db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scraper_ec", description="Scraper Ecuador (Asamblea Nacional)")
    p.add_argument("--db", default=DEFAULT_DB, help=f"Path al SQLite (default: {DEFAULT_DB})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Inicializa la DB").set_defaults(func=cmd_init)

    s = sub.add_parser("importar-csv", help="Importa un CSV de Ppless")
    s.add_argument("csv", help="Path al CSV descargado de proyectosdeley.asambleanacional.gob.ec")
    s.set_defaults(func=cmd_importar_csv)

    s = sub.add_parser(
        "actualizar-csv",
        help="Descarga CSV fresco del portal Ppless v2 (Playwright) y re-importa la lista de proyectos."
    )
    s.add_argument("--no-headless", action="store_true",
                   help="Mostrar el browser (debug). Default: headless")
    s.set_defaults(func=cmd_actualizar_csv)

    s = sub.add_parser(
        "enriquecer-documentos",
        help="Captura URLs de PDFs por proyecto via Playwright (browser headless).",
    )
    s.add_argument("--limit", type=int, default=None, help="Limitar a N proyectos (para testing)")
    s.add_argument("--estado", help="Solo proyectos con este estado")
    s.add_argument("--force", action="store_true",
                   help="Re-enriquecer incluso proyectos con docs ya capturados")
    s.add_argument("--solo-sin-fase", dest="solo_sin_fase", action="store_true",
                   help="Re-procesa solo proyectos con docs cuya fase quedo nula "
                        "(targeted fix tras bug del fallback fase_per_index)")
    s.add_argument("--no-headless", action="store_true",
                   help="Mostrar el browser (debug). Default: headless")
    s.add_argument("--sleep-ms", type=int, default=1000,
                   help="Pausa entre proyectos (ms). Default 1000.")
    s.set_defaults(func=cmd_enriquecer_documentos)

    sub.add_parser("recategorizar", help="Re-clasifica temas no marcados como manuales").set_defaults(func=cmd_recategorizar)

    s = sub.add_parser(
        "scrapear-unificados",
        help="Scrapea con Playwright los grupos de unificacion del portal "
             "Ppless v2 (toggle 'Unificados'). Borra grupos source='portal' "
             "previos y los re-crea con la data actual del portal.",
    )
    s.add_argument("--no-headless", action="store_true",
                   help="Mostrar el browser (debug). Default: headless")
    s.add_argument("--max-pages", type=int, default=100,
                   help="Limite de seguridad en paginas (default 100, real ~25)")
    s.set_defaults(func=cmd_scrapear_unificados)

    s = sub.add_parser(
        "marcar-unificacion",
        help="Crea un grupo de unificacion con N proyectos (manual).",
    )
    s.add_argument("--pls", required=True,
                   help="N. tramites separados por coma. Ej: 480824,480825,480826")
    s.add_argument("--nombre", help="Nombre descriptivo del grupo (opcional)")
    s.add_argument("--descripcion", help="Descripcion mas larga (opcional)")
    s.add_argument("--principal", help="N. tramite del PL principal (default: primero)")
    s.set_defaults(func=cmd_marcar_unificacion)

    sub.add_parser(
        "listar-unificaciones",
        help="Lista todos los grupos de unificacion con sus miembros.",
    ).set_defaults(func=cmd_listar_unificaciones)

    s = sub.add_parser(
        "borrar-unificacion",
        help="Borra un grupo de unificacion por su id.",
    )
    s.add_argument("grupo_id", type=int)
    s.set_defaults(func=cmd_borrar_unificacion)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
