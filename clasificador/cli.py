"""CLI del clasificador ML.

Comandos:

  python -m clasificador.cli train [--db DB] [--eval]
    Entrena el modelo desde proyectos.tema_manual=1 y lo guarda en
    models/clasificador_pe.joblib. Con --eval corre 3-fold CV primero.

  python -m clasificador.cli predict "titulo del PL" ["sumilla"]
    Predice tema + confianza para un texto. Util para debug.

  python -m clasificador.cli reclassify [--apply] [--db DB]
    Re-corre el modelo sobre PLs con tema='Otros':
      - sin --apply: solo registra sugerencias en clasificacion_sugerencias
      - con --apply: aplica cambios con confidence >= 0.85, deja el resto
        como sugerencias pendientes.

  python -m clasificador.cli stats [--db DB]
    Muestra estadisticas: distribucion de temas, sugerencias pendientes.

  python -m clasificador.cli aplicar-decisiones [--db DB]
    Aplica las decisiones (aceptar/rechazar) que Nicolas registro desde
    la seccion "Sugerencias de reclasificacion" de pages/1_Peru.py -
    ver clasificador/decisiones_store.py para el por que del round-trip
    (la UI no puede escribir proyectos.db directo).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from .predict import predict_tema, topk
from .reclassify import aplicar_decisiones, reclassify_otros
from .train import (
    evaluate,
    load_training_data,
    save,
    train_final,
)


def cmd_train(args: argparse.Namespace) -> int:
    textos, labels = load_training_data(args.db)
    print(f"[train] {len(textos):,} ejemplos, {len(set(labels))} clases")
    if args.eval:
        evaluate(textos, labels, k=args.k)
    model = train_final(textos, labels)
    save(model)
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    tema, conf = predict_tema(args.titulo, args.sumilla)
    print(f"Tema:   {tema}")
    print(f"Conf:   {conf:.3f}")
    print("\nTop-5:")
    for t, c in topk(args.titulo, args.sumilla, k=5):
        print(f"  {c:.3f}  {t}")
    return 0


def cmd_reclassify(args: argparse.Namespace) -> int:
    conn = sqlite3.connect(args.db)
    try:
        stats = reclassify_otros(
            conn,
            apply_threshold=args.apply_threshold,
            suggest_threshold=args.suggest_threshold,
            apply=args.apply,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()
    print(f"\n[reclassify] stats: {stats}")
    return 0


def cmd_aplicar_decisiones(args: argparse.Namespace) -> int:
    from .decisiones_store import limpiar_decisiones_aplicadas, list_decisiones_pendientes

    decisiones = list_decisiones_pendientes()
    if not decisiones:
        print("[aplicar-decisiones] sin decisiones pendientes")
        return 0
    conn = sqlite3.connect(args.db)
    try:
        stats = aplicar_decisiones(conn, decisiones)
    finally:
        conn.close()
    limpiar_decisiones_aplicadas(stats["procesadas"])
    print(f"[aplicar-decisiones] aceptadas={stats['aceptadas']} "
          f"rechazadas={stats['rechazadas']} ya_resueltas={stats['ya_resueltas']} "
          f"no_encontradas={stats['no_encontradas']}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    conn = sqlite3.connect(args.db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM proyectos").fetchone()[0]
        manual = conn.execute(
            "SELECT COUNT(*) FROM proyectos WHERE tema_manual=1"
        ).fetchone()[0]
        otros = conn.execute(
            "SELECT COUNT(*) FROM proyectos WHERE tema='Otros'"
        ).fetchone()[0]
        print(f"PLs total: {total}")
        print(f"PLs con tema_manual=1: {manual}")
        print(f"PLs en 'Otros': {otros}")
        print()
        # Tabla sugerencias (si existe)
        try:
            counts = conn.execute(
                """SELECT estado, COUNT(*) FROM clasificacion_sugerencias
                   GROUP BY estado ORDER BY 2 DESC"""
            ).fetchall()
            if counts:
                print("Sugerencias por estado:")
                for estado, n in counts:
                    print(f"  {estado:12s} {n:6d}")
        except sqlite3.OperationalError:
            print("(tabla clasificacion_sugerencias no existe — corre reclassify primero)")
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clasificador", description="ML classifier para temas de PLs")
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("train", help="entrena el modelo desde tema_manual=1")
    pt.add_argument("--db", default="proyectos.db")
    pt.add_argument("--eval", action="store_true", help="corre cross-validation antes")
    pt.add_argument("-k", type=int, default=3, help="folds para CV (default 3)")

    pp = sub.add_parser("predict", help="predice tema para un texto")
    pp.add_argument("titulo", help="titulo del PL")
    pp.add_argument("sumilla", nargs="?", default="", help="sumilla opcional")

    pr = sub.add_parser("reclassify", help="re-corre clasificador sobre 'Otros'")
    pr.add_argument("--db", default="proyectos.db")
    pr.add_argument("--apply", action="store_true",
                    help="aplica cambios con confidence >= apply_threshold")
    pr.add_argument("--apply-threshold", type=float, default=0.85)
    pr.add_argument("--suggest-threshold", type=float, default=0.70)
    pr.add_argument("--dry-run", action="store_true",
                    help="no escribe a la DB, solo cuenta")

    ps = sub.add_parser("stats", help="estadisticas del clasificador")
    ps.add_argument("--db", default="proyectos.db")

    pa = sub.add_parser("aplicar-decisiones",
                        help="aplica aceptar/rechazar registrados desde la UI (pages/1_Peru.py)")
    pa.add_argument("--db", default="proyectos.db")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "train":
        return cmd_train(args)
    if args.cmd == "predict":
        return cmd_predict(args)
    if args.cmd == "reclassify":
        return cmd_reclassify(args)
    if args.cmd == "stats":
        return cmd_stats(args)
    if args.cmd == "aplicar-decisiones":
        return cmd_aplicar_decisiones(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
