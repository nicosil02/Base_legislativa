"""CLI del scraper Ecuador.

Ejemplos de uso:

    python -m scraper_ec.cli init
    python -m scraper_ec.cli importar-csv data/ppless_listado_2025-2029_snapshot.csv
    python -m scraper_ec.cli stats
    python -m scraper_ec.cli query --estado "PROYECTO PRESENTADO"
    python -m scraper_ec.cli query --tema "Tecnología"
    python -m scraper_ec.cli show 480824
    python -m scraper_ec.cli recategorizar
    python -m scraper_ec.cli export --out proyectos_ec.json
"""
from __future__ import annotations

import argparse
import json
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


def cmd_stats(args) -> int:
    db = _db(args)
    try:
        total = db.count_proyectos()
        print(f"Total proyectos: {total}")
        # Por estado
        print("\nPor estado:")
        for r in db.conn.execute(
            "SELECT estado, COUNT(*) c FROM proyectos GROUP BY estado ORDER BY c DESC"
        ):
            print(f"  {r['c']:>4}  {r['estado']}")
        # Por tema
        print("\nPor tema:")
        for r in db.conn.execute(
            "SELECT tema, COUNT(*) c FROM proyectos GROUP BY tema ORDER BY c DESC"
        ):
            tema = r["tema"] or "(sin clasificar)"
            print(f"  {r['c']:>4}  {tema}")
        # Último sync
        last = db.conn.execute(
            "SELECT * FROM sync_runs WHERE finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last:
            print(f"\nÚltimo sync: {last['finished_at']}")
            print(f"  vistos={last['proyectos_vistos']}  "
                  f"nuevos={last['proyectos_nuevos']}  "
                  f"actualizados={last['proyectos_actualizados']}  "
                  f"errores={last['errores']}")
    finally:
        db.close()
    return 0


def cmd_query(args) -> int:
    db = _db(args)
    try:
        sql = "SELECT n_tramite, fec_presentacion, estado, comision_asignada, tema, titulo FROM proyectos WHERE 1=1"
        params: list = []
        if args.estado:
            sql += " AND estado = ?"; params.append(args.estado)
        if args.tema:
            sql += " AND tema = ?"; params.append(args.tema)
        if args.comision:
            sql += " AND comision_asignada LIKE ?"; params.append(f"%{args.comision}%")
        sql += " ORDER BY fec_presentacion DESC"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        for r in db.conn.execute(sql, params):
            titulo = (r["titulo"] or "")[:80]
            print(f"  {r['n_tramite']:<22} {r['fec_presentacion']}  [{r['tema'] or '-'}]  {titulo}")
    finally:
        db.close()
    return 0


def cmd_show(args) -> int:
    db = _db(args)
    try:
        p = db.conn.execute(
            "SELECT * FROM proyectos WHERE n_tramite = ?", (args.n_tramite,)
        ).fetchone()
        if not p:
            print(f"No encontré el proyecto con N. Trámite = {args.n_tramite}")
            return 1
        print(f"\n=== {p['n_tramite']} ===")
        for k in p.keys():
            print(f"  {k:<22} {p[k]}")
        propon = db.conn.execute(
            "SELECT nombre, tipo FROM proponentes WHERE n_tramite = ? ORDER BY orden",
            (args.n_tramite,),
        ).fetchall()
        if propon:
            print(f"\n  Proponentes ({len(propon)}):")
            for pr in propon:
                print(f"    - {pr['nombre']}  ({pr['tipo']})")
        hist = db.conn.execute(
            "SELECT changed_at, campo, valor_antes, valor_despues "
            "FROM historial_cambios WHERE n_tramite = ? ORDER BY id DESC LIMIT 20",
            (args.n_tramite,),
        ).fetchall()
        if hist:
            print(f"\n  Historial ({len(hist)} cambios):")
            for h in hist:
                print(f"    {h['changed_at']} | {h['campo']}: "
                      f"{(h['valor_antes'] or '')[:40]!r} → {(h['valor_despues'] or '')[:40]!r}")
    finally:
        db.close()
    return 0


def cmd_actualizar_csv(args) -> int:
    """Descarga CSV fresco del portal Ppless v2 (Playwright) y re-importa.

    Asi se sincroniza la lista de proyectos con el portal: aparecen nuevos
    PLs y se actualizan los existentes. Equivalente a hacer en local:
       1) Abrir Ppless v2, clickear tab 2.0, clickear boton CSV
       2) python -m scraper_ec.cli importar-csv <archivo>
    """
    from pathlib import Path
    from scraper_ec.playwright_detail import download_csv
    from scraper_ec.csv_importer import import_csv

    repo_root = Path(__file__).resolve().parent.parent
    csv_path = repo_root / "data" / "ppless_listado_2025-2029_snapshot.csv"

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


def cmd_snapshot(args) -> int:
    """Comprime proyectos_ec.db a data/proyectos_ec.db.gz.

    El snapshot es lo que Streamlit Cloud usa al arrancar (el filesystem
    es efimero, no puede persistir la DB enriquecida). Despues de
    enriquecer documentos localmente, corre este comando + commit + push.
    """
    import gzip
    import shutil
    from pathlib import Path

    repo_root = Path(args.db).resolve().parent if args.db else Path.cwd()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"ERROR: no encontre {db_path}")
        return 1

    # data/ esta a nivel del repo root. Buscamos el directorio data/ subiendo.
    here = db_path.parent
    data_dir = here / "data"
    if not data_dir.exists():
        # Subir hasta encontrarlo
        for _ in range(5):
            here = here.parent
            if (here / "data").exists():
                data_dir = here / "data"
                break
    if not data_dir.exists():
        data_dir = db_path.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

    out_path = data_dir / "proyectos_ec.db.gz"
    print(f"Comprimiendo {db_path.name} ({db_path.stat().st_size:,} bytes) → {out_path.name}...")
    with db_path.open("rb") as f_in, gzip.open(out_path, "wb", compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)
    print(f"Snapshot listo: {out_path} ({out_path.stat().st_size:,} bytes)")
    print()
    print("Para sincronizar con Streamlit Cloud:")
    print(f"  git add {out_path.relative_to(here.parent if data_dir.parent != here else here)}")
    print('  git commit -m "Snapshot EC con documentos enriquecidos"')
    print("  git push")
    return 0


def cmd_fix_typos(args) -> int:
    """Aplica COMISION_TYPOS a la data ya en la DB. Útil tras agregar nuevos
    typos al diccionario, o tras una primera importación con typos viejos."""
    from scraper_ec.csv_importer import COMISION_TYPOS
    from scraper_ec.db import now_iso

    db = _db(args)
    try:
        now = now_iso()
        total_fixed = 0
        for raw, fixed in COMISION_TYPOS.items():
            cur = db.conn.execute(
                "SELECT COUNT(*) FROM proyectos WHERE comision_asignada = ?",
                (raw,),
            ).fetchone()
            n = cur[0]
            if n == 0:
                continue
            print(f"  '{raw}' → '{fixed}' ({n} proyectos)")
            # Update + registrar en historial_cambios
            for r in db.conn.execute(
                "SELECT n_tramite FROM proyectos WHERE comision_asignada = ?",
                (raw,),
            ).fetchall():
                with db.tx() as c:
                    c.execute(
                        "UPDATE proyectos SET comision_asignada=?, last_changed_at=? WHERE n_tramite=?",
                        (fixed, now, r["n_tramite"]),
                    )
                    c.execute(
                        "INSERT INTO historial_cambios (n_tramite, changed_at, campo, valor_antes, valor_despues) "
                        "VALUES (?,?,?,?,?)",
                        (r["n_tramite"], now, "comision_asignada", raw, fixed),
                    )
            total_fixed += n
        if total_fixed == 0:
            print("No hay typos pendientes — DB ya limpia.")
        else:
            print(f"\nTotal corregido: {total_fixed} proyectos.")
    finally:
        db.close()
    return 0


def cmd_enriquecer_documentos(args) -> int:
    """Itera proyectos abriendo el modal de detalle vía Playwright para
    capturar los URLs de PDFs."""
    try:
        from scraper_ec.playwright_detail import enrich_documentos
    except ImportError:
        print("Falta playwright. Instalá con: pip install playwright && python -m playwright install chromium")
        return 1

    db = _db(args)
    try:
        # Lista de N. Trámite a enriquecer. Por default elegimos proyectos
        # que NO tienen documentos en la DB (los que faltan procesar),
        # ordenados por fec_presentacion DESC (mas recientes primero — son
        # los que mas interesan). Con --force, ignora el filtro y procesa
        # todos los que matcheen --estado / --limit.
        params: list = []
        sql = "SELECT n_tramite FROM proyectos"
        where = []
        if args.estado:
            where.append("estado = ?")
            params.append(args.estado)
        if getattr(args, "solo_sin_fase", False):
            # Modo quirurgico: solo proyectos con al menos 1 doc cuya fase
            # quedo nula (bug viejo del fallback fase_per_index). Re-procesa
            # esos para que el fix nuevo asigne la fase correctamente.
            where.append(
                "n_tramite IN (SELECT DISTINCT n_tramite FROM documentos "
                "WHERE fase IS NULL OR fase = '')"
            )
        elif not args.force:
            # Default: solo proyectos sin documentos enriquecidos
            where.append("n_tramite NOT IN (SELECT DISTINCT n_tramite FROM documentos)")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY fec_presentacion DESC"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        n_tramites = [r["n_tramite"] for r in db.conn.execute(sql, params).fetchall()]

        def progress(ntr, idx, total):
            print(f"[{idx}/{total}] {ntr}")

        # En modo --solo-sin-fase o --force, no skipear los que ya tienen docs:
        # justamente queremos re-procesar para sobrescribir las fases mal asignadas.
        skip_with_docs = not (args.force or getattr(args, "solo_sin_fase", False))

        stats = enrich_documentos(
            db,
            n_tramites=n_tramites,
            headless=not args.no_headless,
            skip_with_docs=skip_with_docs,
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


def cmd_marcar_unificacion(args) -> int:
    """Crea un grupo de unificacion con los PLs dados.

    Uso:
      python -m scraper_ec.cli marcar-unificacion --pls 480824,480825,480826
          --nombre "Reformas a Inquilinato"
          --principal 480824   (opcional, default primero)
    """
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


def cmd_export(args) -> int:
    db = _db(args)
    out_path = Path(args.out).resolve()
    try:
        rows = db.conn.execute(
            "SELECT * FROM proyectos ORDER BY fec_presentacion DESC"
        ).fetchall()
        data = []
        for r in rows:
            d = dict(r)
            propon = db.conn.execute(
                "SELECT nombre, tipo, orden FROM proponentes WHERE n_tramite = ? ORDER BY orden",
                (r["n_tramite"],),
            ).fetchall()
            d["proponentes"] = [dict(p) for p in propon]
            data.append(d)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Exportado: {len(data)} proyectos → {out_path}")
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

    sub.add_parser("stats", help="Estadísticas de la DB").set_defaults(func=cmd_stats)

    s = sub.add_parser("query", help="Lista proyectos con filtros")
    s.add_argument("--estado")
    s.add_argument("--tema")
    s.add_argument("--comision")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("show", help="Muestra detalle de un proyecto por N. Trámite")
    s.add_argument("n_tramite")
    s.set_defaults(func=cmd_show)

    sub.add_parser("fix-typos", help="Corrige typos conocidos en comisiones (ej: 'Bodiversidad')").set_defaults(func=cmd_fix_typos)

    s = sub.add_parser(
        "actualizar-csv",
        help="Descarga CSV fresco del portal Ppless v2 (Playwright) y re-importa la lista de proyectos."
    )
    s.add_argument("--no-headless", action="store_true",
                   help="Mostrar el browser (debug). Default: headless")
    s.set_defaults(func=cmd_actualizar_csv)

    sub.add_parser(
        "snapshot",
        help="Comprime proyectos_ec.db a data/proyectos_ec.db.gz para sync con Streamlit Cloud."
    ).set_defaults(func=cmd_snapshot)

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

    # ---------- unificaciones ----------
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

    s = sub.add_parser("export", help="Exporta a JSON")
    s.add_argument("--out", default="proyectos_ec.json")
    s.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
